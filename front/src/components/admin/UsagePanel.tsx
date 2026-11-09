import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import {
  CLAUDE_OVERAGE_RATE_LIMIT_ID,
  GENERAL_CLAUDE_RATE_LIMIT_ID,
  GENERAL_CODEX_RATE_LIMIT_ID,
  GPT_RESERVE_RATE_LIMIT_ID,
  SECONDARY_CODEX_RATE_LIMIT_ID,
} from "../../services/types";
import type {
  CodexRateLimitSample,
  CodexUsageConfig,
  CodexUsageProvider,
  CodexUsageStats,
  UsageSamplesImportResult,
} from "../../services/types";
import type { WebBotClient } from "../../services/webBotClient";
import { getErrorMessage } from "../../utils/errorMessage";
import { codexConsumptionBars, codexConsumptionCurve, type QuotaCurveSegment } from "../../utils/codexConsumptionRate";
import "./UsagePanel.css";

export type UsagePanelProvider = "codex" | "claude";

const USAGE_PROVIDERS: readonly UsagePanelProvider[] = ["codex", "claude"];

const USAGE_PROVIDER_LABELS: Record<UsagePanelProvider, string> = {
  codex: "Codex",
  claude: "Claude",
};

type UsagePanelProps = {
  client: WebBotClient;
  provider: UsagePanelProvider;
  onProviderChange: (provider: UsagePanelProvider) => void;
  refreshKey?: number;
};

type ProviderUsageViewProps = {
  client: WebBotClient;
  provider: UsagePanelProvider;
  onTimeBasisChange: (utcOffset: string) => void;
};

const numberFormat = new Intl.NumberFormat("zh-CN");
const creditsValueFormat = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });

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

type QuickRangeKey = "today" | "7d" | "30d" | "90d" | "all";

const QUICK_RANGES: readonly { key: QuickRangeKey; label: string; days: number | null }[] = [
  { key: "today", label: "今天", days: 1 },
  { key: "7d", label: "近 7 天", days: 7 },
  { key: "30d", label: "近 30 天", days: 30 },
  { key: "90d", label: "近 90 天", days: 90 },
  { key: "all", label: "全部", days: null },
];

const DEFAULT_QUICK_RANGE: QuickRangeKey = "30d";

function defaultRange(today: string) {
  const endDate = today || formatDateValue(new Date());
  return {
    startDate: subtractDays(endDate, 29) || endDate,
    endDate,
  };
}

function formatImportNotice(result: UsageSamplesImportResult) {
  const skipped = [
    result.duplicates ? `${numberFormat.format(result.duplicates)} 条已存在` : "",
    result.invalid ? `${numberFormat.format(result.invalid)} 条无效` : "",
  ].filter(Boolean).join("，");
  if (!result.inserted) {
    return `没有新的额度样本${skipped ? `（${skipped}）` : ""}。`;
  }
  const inserted = USAGE_PROVIDERS
    .filter((id) => result.insertedByProvider[id] > 0)
    .map((id) => `${USAGE_PROVIDER_LABELS[id]} ${numberFormat.format(result.insertedByProvider[id])}`)
    .join("，");
  return `已合并 ${numberFormat.format(result.inserted)} 条额度样本（${inserted}）${skipped ? `；跳过 ${skipped}` : ""}。`;
}

function providerLabel(provider: CodexUsageProvider) {
  return provider.label || (provider.kind === "openai_official" ? "OpenAI 官方" : "无法识别");
}

const percentValueFormat = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 1 });
const durationDaysFormat = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });
const consumptionRateFormat = new Intl.NumberFormat("zh-CN", { maximumSignificantDigits: 3 });
const RATE_LIMIT_AXIS_STEP_PERCENT = 10;
const RATE_LIMIT_AXIS_INTERVALS = 4;
const WEEKLY_WINDOW_MINUTES = 7 * 24 * 60;
const CONSUMPTION_BAR_TARGET = 32;
const MINUTE_MS = 60 * 1000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;
const CONSUMPTION_INTERVALS_MS = [
  MINUTE_MS,
  2 * MINUTE_MS,
  5 * MINUTE_MS,
  10 * MINUTE_MS,
  15 * MINUTE_MS,
  30 * MINUTE_MS,
  HOUR_MS,
  2 * HOUR_MS,
  3 * HOUR_MS,
  6 * HOUR_MS,
  12 * HOUR_MS,
  DAY_MS,
  2 * DAY_MS,
  7 * DAY_MS,
  14 * DAY_MS,
  30 * DAY_MS,
];
type RateLimitSecondaryMetric = "duration" | "consumption" | "credits";

function formatPercentValue(value: number) {
  return `${percentValueFormat.format(value)}%`;
}

function remainingPercent(sample: CodexRateLimitSample) {
  return Math.min(100, Math.max(0, 100 - sample.usedPercent));
}

function creditsValue(sample: CodexRateLimitSample) {
  if (typeof sample.creditsBalance !== "string" || !sample.creditsBalance.trim()) return null;
  const value = Number(sample.creditsBalance);
  return Number.isFinite(value) && value >= 0 ? value : null;
}

function formatCreditsValue(value: number | null) {
  return value === null ? "—" : creditsValueFormat.format(value);
}

function creditsAxisBounds(samples: CodexRateLimitSample[]) {
  const values = samples
    .map(creditsValue)
    .filter((value): value is number => value !== null);
  if (!values.length) return null;
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (min === max) {
    const padding = Math.max(max * 0.1, 1);
    min = Math.max(0, min - padding);
    max += padding;
  } else {
    const padding = (max - min) * 0.1;
    min = Math.max(0, min - padding);
    max += padding;
  }
  return { min, max };
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

function sampledAtOffsetMinutes(value: string) {
  if (value.endsWith("Z")) return 0;
  const match = /([+-])(\d{2}):(\d{2})$/.exec(value);
  if (!match) return null;
  const minutes = Number(match[2]) * 60 + Number(match[3]);
  return match[1] === "-" ? -minutes : minutes;
}

function fixedConsumptionTimeDomain(
  minTimestamp: number,
  maxTimestamp: number,
  samples: CodexRateLimitSample[],
) {
  const sampleRange = maxTimestamp - minTimestamp;
  if (!Number.isFinite(sampleRange) || sampleRange <= 0) return null;
  const targetInterval = sampleRange / CONSUMPTION_BAR_TARGET;
  const interval = CONSUMPTION_INTERVALS_MS.find((candidate) => candidate >= targetInterval)
    ?? Math.ceil(targetInterval / DAY_MS) * DAY_MS;
  const explicitOffsetMinutes = sampledAtOffsetMinutes(samples[0]?.sampledAt || "");
  const offsetMs = (explicitOffsetMinutes ?? -new Date(minTimestamp).getTimezoneOffset()) * MINUTE_MS;
  const start = Math.floor((minTimestamp + offsetMs) / interval) * interval - offsetMs;
  const alignedEnd = Math.ceil((maxTimestamp + offsetMs) / interval) * interval - offsetMs;
  const end = Math.max(start + interval, alignedEnd);
  return {
    start,
    end,
    count: Math.max(1, Math.round((end - start) / interval)),
  };
}

function formatSampleTimestamp(timestamp: number, samples: CodexRateLimitSample[]) {
  const closest = samples.reduce<{ distance: number; value: string } | null>((best, sample) => {
    const sampleTimestamp = Date.parse(sample.sampledAt);
    const distance = Math.abs(sampleTimestamp - timestamp);
    return Number.isFinite(distance) && (!best || distance < best.distance)
      ? { distance, value: sample.sampledAt }
      : best;
  }, null);
  const offsetMinutes = closest ? sampledAtOffsetMinutes(closest.value) : null;
  const date = new Date(timestamp + (offsetMinutes ?? 0) * 60 * 1000);
  const read = (part: "year" | "month" | "day" | "hour" | "minute") => {
    if (offsetMinutes !== null) {
      if (part === "year") return date.getUTCFullYear();
      if (part === "month") return date.getUTCMonth() + 1;
      if (part === "day") return date.getUTCDate();
      if (part === "hour") return date.getUTCHours();
      return date.getUTCMinutes();
    }
    if (part === "year") return date.getFullYear();
    if (part === "month") return date.getMonth() + 1;
    if (part === "day") return date.getDate();
    if (part === "hour") return date.getHours();
    return date.getMinutes();
  };
  const pad = (value: number) => String(value).padStart(2, "0");
  const month = pad(read("month"));
  const day = pad(read("day"));
  return {
    date: `${read("year")}/${month}/${day}`,
    time: `${pad(read("hour"))}:${pad(read("minute"))}`,
  };
}

function formatConsumptionPeriod(
  startX: number,
  endX: number,
  minTimestamp: number,
  timestampRange: number,
  plotLeft: number,
  plotWidth: number,
  samples: CodexRateLimitSample[],
) {
  const formatX = (x: number) => {
    const timestamp = minTimestamp + ((x - plotLeft) / plotWidth) * timestampRange;
    return formatSampleTimestamp(Math.round(timestamp / MINUTE_MS) * MINUTE_MS, samples);
  };
  const start = formatX(startX);
  const end = formatX(endX);
  const endText = start.date === end.date ? end.time : `${end.date}-${end.time}`;
  return `${start.date}-${start.time}~${endText}`;
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
  if (normalized === "max") return "Max";
  if (normalized === "team") return "Team";
  if (normalized === "enterprise") return "Enterprise";
  return planType?.trim() || "套餐未知";
}

function compareSampledAt(left: CodexRateLimitSample, right: CodexRateLimitSample) {
  const leftTimestamp = Date.parse(left.sampledAt);
  const rightTimestamp = Date.parse(right.sampledAt);
  if (Number.isFinite(leftTimestamp) && Number.isFinite(rightTimestamp)) {
    return leftTimestamp - rightTimestamp;
  }
  if (Number.isFinite(leftTimestamp)) return -1;
  if (Number.isFinite(rightTimestamp)) return 1;
  return 0;
}

const DEFAULT_CHART_WIDTH = 640;
const MIN_CHART_WIDTH = 280;

function useMeasuredWidth(fallback: number) {
  const [width, setWidth] = useState(fallback);
  const observerRef = useRef<ResizeObserver | null>(null);
  const ref = useCallback((node: HTMLDivElement | null) => {
    observerRef.current?.disconnect();
    observerRef.current = null;
    if (!node || typeof ResizeObserver === "undefined") return;
    const update = () => {
      const next = Math.round(node.clientWidth);
      if (next > 0) setWidth(Math.max(MIN_CHART_WIDTH, next));
    };
    update();
    observerRef.current = new ResizeObserver(update);
    observerRef.current.observe(node);
  }, []);
  return { width, ref };
}

type PaceTone = "good" | "warning" | "critical" | "neutral";

type QuotaPace = {
  tone: PaceTone;
  label: string;
  hint: string;
  timePercent: number | null;
  exhaustText: string;
};

/**
 * Compare the remaining quota with the remaining share of the window.  When
 * quota outlasts time the bucket is on pace; the latest consumption rate then
 * estimates whether it runs out before the next reset.
 */
function quotaPace(sample: CodexRateLimitSample, latestRate: number | null): QuotaPace {
  const remaining = remainingPercent(sample);
  const hasReset = Number.isFinite(Date.parse(sample.resetsAt)) && Number.isFinite(Date.parse(sample.sampledAt));
  const timePercent = hasReset ? Math.min(100, Math.max(0, remainingDurationPercent(sample))) : null;
  const resetMs = remainingDurationMs(sample);
  let exhaustText = "—";
  if (remaining <= 0) exhaustText = "已耗尽";
  else if (latestRate !== null) {
    const exhaustMs = latestRate > 0 ? (remaining / latestRate) * HOUR_MS : Infinity;
    exhaustText = hasReset && exhaustMs >= resetMs
      ? "重置前充足"
      : Number.isFinite(exhaustMs) ? `约 ${formatRemainingDuration(exhaustMs)}` : "重置前充足";
  }
  if (remaining <= 0) {
    return { tone: "critical", label: "已耗尽", hint: "额度已用完，等待重置", timePercent, exhaustText };
  }
  if (timePercent === null) {
    return { tone: "neutral", label: "节奏未知", hint: "缺少有效的重置时间", timePercent, exhaustText };
  }
  const delta = remaining - timePercent;
  const hint = `剩余额度 ${formatPercentValue(remaining)}，窗口剩余时间 ${formatPercentValue(timePercent)}`;
  if (delta >= 0) return { tone: "good", label: "节奏充裕", hint, timePercent, exhaustText };
  if (delta >= -15) return { tone: "warning", label: "略快于均速", hint, timePercent, exhaustText };
  return { tone: "critical", label: "消耗偏快", hint, timePercent, exhaustText };
}

type ChartPoint = {
  x: number;
  y: number;
};

type TimedChartPoint = ChartPoint & {
  timestamp: number;
};

// Keep roughly one curve knot per 12 viewBox units.  The resulting bucket
// width is always derived from elapsed time, so the amount of smoothing tracks
// the visible x-axis span instead of the number of collected samples.
const SMOOTHING_KNOT_SPACING = 12;

function linearPath(points: ChartPoint[]) {
  if (!points.length) return "";
  return [
    `M ${points[0].x} ${points[0].y}`,
    ...points.slice(1).map((point) => `L ${point.x} ${point.y}`),
  ].join(" ");
}

type TemporalCurve = {
  points: TimedChartPoint[];
  cumulativeAreas: number[];
};

function buildTemporalCurve(points: TimedChartPoint[]): TemporalCurve {
  const cumulativeAreas = [0];
  for (let index = 1; index < points.length; index += 1) {
    const previous = points[index - 1];
    const next = points[index];
    const elapsed = next.timestamp - previous.timestamp;
    const area = elapsed > 0 ? ((previous.y + next.y) / 2) * elapsed : 0;
    cumulativeAreas.push(cumulativeAreas[index - 1] + area);
  }
  return { points, cumulativeAreas };
}

function temporalSegmentIndex(points: TimedChartPoint[], timestamp: number) {
  let low = 1;
  let high = points.length - 1;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (points[middle].timestamp < timestamp) low = middle + 1;
    else high = middle;
  }
  return low;
}

function temporalPointAt(curve: TemporalCurve, timestamp: number): TimedChartPoint {
  const { points } = curve;
  const first = points[0];
  const last = points[points.length - 1];
  if (timestamp <= first.timestamp) return { ...first, timestamp };
  if (timestamp >= last.timestamp) return { ...last, timestamp };
  const index = temporalSegmentIndex(points, timestamp);
  const previous = points[index - 1];
  const next = points[index];
  const width = next.timestamp - previous.timestamp;
  if (width <= 0) return { ...next, timestamp };
  const ratio = (timestamp - previous.timestamp) / width;
  return {
    timestamp,
    x: previous.x + (next.x - previous.x) * ratio,
    y: previous.y + (next.y - previous.y) * ratio,
  };
}

function temporalAreaAt(curve: TemporalCurve, timestamp: number) {
  const { points, cumulativeAreas } = curve;
  const first = points[0];
  const lastIndex = points.length - 1;
  if (timestamp <= first.timestamp) return 0;
  if (timestamp >= points[lastIndex].timestamp) return cumulativeAreas[lastIndex];
  const index = temporalSegmentIndex(points, timestamp);
  const previous = points[index - 1];
  const next = points[index];
  const elapsed = timestamp - previous.timestamp;
  const width = next.timestamp - previous.timestamp;
  if (width <= 0) return cumulativeAreas[index - 1];
  const ratio = elapsed / width;
  const value = previous.y + (next.y - previous.y) * ratio;
  return cumulativeAreas[index - 1] + ((previous.y + value) / 2) * elapsed;
}

/**
 * Average the piecewise-linear source curve over a time interval.  Weighting
 * by elapsed time keeps a burst of samples from changing the result merely by
 * increasing its sample count.
 */
function averageTimedPoint(
  curve: TemporalCurve,
  start: number,
  end: number,
) {
  const { points } = curve;
  const first = points[0];
  const last = points[points.length - 1];
  const intervalStart = Math.max(start, first.timestamp);
  const intervalEnd = Math.min(end, last.timestamp);
  if (!(intervalEnd > intervalStart)) return null;

  const elapsed = intervalEnd - intervalStart;
  const weightedY = temporalAreaAt(curve, intervalEnd) - temporalAreaAt(curve, intervalStart);
  if (!(elapsed > 0) || !Number.isFinite(weightedY)) return null;
  const averageY = weightedY / elapsed;
  if (!Number.isFinite(averageY)) return null;
  const timestamp = (intervalStart + intervalEnd) / 2;
  const midpoint = temporalPointAt(curve, timestamp);
  return {
    ...midpoint,
    timestamp,
    y: averageY,
  };
}

function collapseDuplicateTimedPoints(points: TimedChartPoint[]) {
  if (points.length <= 2) return points;
  const first = points[0];
  const last = points[points.length - 1];
  const interior: TimedChartPoint[] = [];
  for (const point of points.slice(1, -1)) {
    // Segment endpoints are reset anchors, so never replace them with a
    // duplicate sample at the same instant.
    if (point.timestamp === first.timestamp || point.timestamp === last.timestamp) continue;
    const previous = interior.at(-1);
    if (previous?.timestamp === point.timestamp) {
      interior[interior.length - 1] = {
        ...previous,
        x: (previous.x + point.x) / 2,
        y: (previous.y + point.y) / 2,
      };
    } else {
      interior.push(point);
    }
  }
  return [first, ...interior, last];
}

/**
 * Reduce dense samples using elapsed time rather than a fixed number of points.
 * The bucket width is derived from the visible sample time range, so the
 * amount of detail adapts when the x-axis span changes.
 */
function temporalSmoothSegment(
  points: TimedChartPoint[],
  timestampRange: number,
  domainStart: number,
  plotWidth: number,
) {
  if (
    !Number.isFinite(timestampRange)
    || timestampRange <= 0
    || !Number.isFinite(domainStart)
    || !Number.isFinite(plotWidth)
    || plotWidth <= 0
  ) return points;
  const bucketCount = Math.max(1, Math.floor(plotWidth / SMOOTHING_KNOT_SPACING));
  const bucketWidth = timestampRange / bucketCount;
  if (bucketWidth <= 0) return points;

  const normalizedPoints = collapseDuplicateTimedPoints(points);
  if (normalizedPoints.length <= 2) return normalizedPoints;
  if (normalizedPoints.some((point, index) => (
    index > 0 && point.timestamp <= normalizedPoints[index - 1].timestamp
  ))) {
    return normalizedPoints;
  }
  const first = normalizedPoints[0];
  const last = normalizedPoints[normalizedPoints.length - 1];
  const curve = buildTemporalCurve(normalizedPoints);
  const bucketIndexes = new Set<number>();
  for (const point of normalizedPoints.slice(1, -1)) {
    if (!Number.isFinite(point.timestamp)) continue;
    const bucketIndex = Math.floor((point.timestamp - domainStart) / bucketWidth);
    bucketIndexes.add(bucketIndex);
  }
  const representatives = [...bucketIndexes]
    .sort((left, right) => left - right)
    .map((bucketIndex) => averageTimedPoint(
      curve,
      domainStart + bucketIndex * bucketWidth,
      domainStart + (bucketIndex + 1) * bucketWidth,
    ))
    .filter((point): point is TimedChartPoint => Boolean(point)
      && point.timestamp > first.timestamp
      && point.timestamp < last.timestamp);
  return [
    first,
    ...representatives,
    last,
  ];
}

function monotoneTangents(points: ChartPoint[]) {
  const slopes = points.slice(1).map((point, index) => {
    const previous = points[index];
    return (point.y - previous.y) / (point.x - previous.x);
  });
  if (slopes.some((slope) => !Number.isFinite(slope))) return null;

  const tangents = Array.from({ length: points.length }, () => 0);
  if (slopes.length === 1) {
    tangents[0] = slopes[0];
    tangents[1] = slopes[0];
    return tangents;
  }

  const endpointTangent = (atEnd: boolean) => {
    const last = points.length - 1;
    const firstSlope = atEnd ? slopes[last - 1] : slopes[0];
    const secondSlope = atEnd ? slopes[last - 2] : slopes[1];
    const firstWidth = atEnd
      ? points[last].x - points[last - 1].x
      : points[1].x - points[0].x;
    const secondWidth = atEnd
      ? points[last - 1].x - points[last - 2].x
      : points[2].x - points[1].x;
    if (firstWidth <= 0 || secondWidth <= 0) return null;
    let tangent = ((2 * firstWidth + secondWidth) * firstSlope - firstWidth * secondSlope)
      / (firstWidth + secondWidth);
    // The one-sided estimate must not introduce an extremum that is absent
    // from the source points, nor overshoot a neighbouring slope reversal.
    if (!Number.isFinite(tangent) || tangent * firstSlope <= 0) tangent = 0;
    else if (firstSlope * secondSlope < 0 && Math.abs(tangent) > Math.abs(3 * firstSlope)) {
      tangent = 3 * firstSlope;
    }
    return tangent;
  };

  const firstTangent = endpointTangent(false);
  const lastTangent = endpointTangent(true);
  if (firstTangent === null || lastTangent === null) return null;
  tangents[0] = firstTangent;
  tangents[tangents.length - 1] = lastTangent;
  for (let index = 1; index < points.length - 1; index += 1) {
    const previousSlope = slopes[index - 1];
    const nextSlope = slopes[index];
    if (previousSlope * nextSlope <= 0) {
      tangents[index] = 0;
      continue;
    }
    const previousWidth = points[index].x - points[index - 1].x;
    const nextWidth = points[index + 1].x - points[index].x;
    const firstWeight = 2 * nextWidth + previousWidth;
    const secondWeight = nextWidth + 2 * previousWidth;
    tangents[index] = (firstWeight + secondWeight)
      / (firstWeight / previousSlope + secondWeight / nextSlope);
  }
  if (tangents.some((tangent) => !Number.isFinite(tangent))) return null;
  return tangents;
}

function appendLinearSegments(segments: QuotaCurveSegment[], points: ChartPoint[]) {
  for (let index = 1; index < points.length; index += 1) {
    segments.push({ start: points[index - 1], end: points[index] });
  }
}

function appendSmoothSegment(
  segments: QuotaCurveSegment[],
  points: TimedChartPoint[],
  timestampRange: number,
  domainStart: number,
  plotWidth: number,
) {
  if (!Number.isFinite(timestampRange) || timestampRange <= 0) {
    appendLinearSegments(segments, points);
    return;
  }
  const reduced = temporalSmoothSegment(points, timestampRange, domainStart, plotWidth);
  if (reduced.length <= 1) return;
  if (
    reduced.length === 2
    || reduced.some((point, index) => index > 0 && point.x <= reduced[index - 1].x)
  ) {
    appendLinearSegments(segments, reduced);
    return;
  }

  const tangents = monotoneTangents(reduced);
  if (!tangents) {
    appendLinearSegments(segments, reduced);
    return;
  }

  for (let index = 1; index < reduced.length; index += 1) {
    const current = reduced[index - 1];
    const next = reduced[index];
    const width = next.x - current.x;
    segments.push({
      start: current,
      end: next,
      controls: [
        current.y + (tangents[index - 1] * width) / 3,
        next.y - (tangents[index] * width) / 3,
      ],
    });
  }
}

function smoothQuotaCurve(
  points: TimedChartPoint[],
  resetBoundaryPairs: Set<string>,
  timestampRange: number,
  domainStart: number,
  plotWidth: number,
) {
  const segments: QuotaCurveSegment[] = [];
  let segmentStart = 0;
  for (let index = 1; index < points.length; index += 1) {
    const isBoundary = resetBoundaryPairs.has(`${index - 1}:${index}`);
    if (!isBoundary) continue;

    appendSmoothSegment(segments, points.slice(segmentStart, index), timestampRange, domainStart, plotWidth);
    segments.push({ start: points[index - 1], end: points[index], reset: true });
    segmentStart = index;
  }
  appendSmoothSegment(segments, points.slice(segmentStart), timestampRange, domainStart, plotWidth);
  return segments;
}

function quotaCurvePath(segments: QuotaCurveSegment[]) {
  if (!segments.length) return "";
  const commands = [`M ${segments[0].start.x} ${segments[0].start.y}`];
  for (const { start, end, controls } of segments) {
    const width = end.x - start.x;
    commands.push(controls
      ? `C ${start.x + width / 3} ${controls[0]} ${end.x - width / 3} ${controls[1]} ${end.x} ${end.y}`
      : `L ${end.x} ${end.y}`);
  }
  return commands.join(" ");
}

function CodexRateLimitBucketChart({
  label,
  samples,
  secondaryMetric,
  providerName,
}: {
  label: string;
  samples: CodexRateLimitSample[];
  secondaryMetric: RateLimitSecondaryMetric;
  providerName: string;
}) {
  const orderedSamples = useMemo(
    () => [...samples].sort(compareSampledAt),
    [samples],
  );
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const gradientId = `usage-quota-area-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const chartWidth = useMeasuredWidth(DEFAULT_CHART_WIDTH);
  const latest = orderedSamples.at(-1);
  if (!latest) {
    return (
      <article className="codex-usage-rate-limit-group">
        <h4>{label}</h4>
        <p className="codex-usage-empty-state">
          {label === `通用 ${providerName}` ? `暂无通用 ${providerName} 限额样本。` : `暂无 ${label} 限额样本。`}
        </p>
      </article>
    );
  }

  // Size the viewBox to the rendered width so labels keep their native size
  // and the plot keeps a fixed height regardless of how wide the card is.
  const width = chartWidth.width;
  const height = 200;
  const narrow = width < 480;
  const left = narrow ? 44 : 56;
  const right = narrow ? 48 : 60;
  const top = 26;
  const bottom = 30;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const timestamps = orderedSamples.map((sample) => Date.parse(sample.sampledAt));
  const hasValidTimestamps = timestamps.every(Number.isFinite);
  const minTimestamp = hasValidTimestamps ? timestamps[0] : 0;
  const maxTimestamp = hasValidTimestamps ? timestamps[timestamps.length - 1] : 0;
  const consumptionTimeDomain = hasValidTimestamps
    ? fixedConsumptionTimeDomain(minTimestamp, maxTimestamp, orderedSamples)
    : null;
  const timestampRange = maxTimestamp - minTimestamp;
  const axisBounds = rateLimitAxisBounds(orderedSamples);
  const axisRange = axisBounds.max - axisBounds.min;
  const creditSamples = orderedSamples.filter((sample) => (
    sample.windowMinutes === WEEKLY_WINDOW_MINUTES && creditsValue(sample) !== null
  ));
  const creditsBounds = creditsAxisBounds(creditSamples);
  const axisTicks = Array.from(
    { length: RATE_LIMIT_AXIS_INTERVALS + 1 },
    (_, index) => axisBounds.min + (axisRange * index) / RATE_LIMIT_AXIS_INTERVALS,
  );
  const yForPercent = (value: number) => (
    top + ((axisBounds.max - value) / axisRange) * plotHeight
  );
  const yForCredits = (value: number) => (
    creditsBounds
      ? top + ((creditsBounds.max - value) / (creditsBounds.max - creditsBounds.min)) * plotHeight
      : top + plotHeight / 2
  );
  const points = orderedSamples.map((sample, index) => ({
    x: left + Math.min(1, Math.max(0, (
      orderedSamples.length === 1
        ? 0.5
        : timestampRange > 0
          ? (timestamps[index] - minTimestamp) / timestampRange
          : index / (orderedSamples.length - 1)
    ))) * plotWidth,
    timestamp: hasValidTimestamps ? timestamps[index] : index,
    quotaY: yForPercent(remainingPercent(sample)),
    durationY: yForPercent(remainingDurationPercent(sample)),
    creditsY: sample.windowMinutes === WEEKLY_WINDOW_MINUTES && creditsValue(sample) !== null
      ? yForCredits(creditsValue(sample) as number)
      : null,
  }));
  const resetBoundaryPairs = new Set<string>();
  // The exact reset instant is not sampled.  The nearest observations on its
  // two sides are therefore the stable extrema anchors to keep verbatim.
  for (let index = 1; index < orderedSamples.length; index += 1) {
    const previousResetAt = Date.parse(orderedSamples[index - 1].resetsAt);
    const currentResetAt = Date.parse(orderedSamples[index].resetsAt);
    const previousSampledAt = Date.parse(orderedSamples[index - 1].sampledAt);
    const currentSampledAt = Date.parse(orderedSamples[index].sampledAt);
    // A reset is either observed between two samples or accompanied by a
    // changed deadline and a quota refill.  The crossing check also handles
    // immediate post-reset usage, where no refill is visible in the sample.
    const resetTimestampChanged = previousResetAt !== currentResetAt;
    const quotaJumped = remainingPercent(orderedSamples[index])
      > remainingPercent(orderedSamples[index - 1]);
    const resetOccurredBetweenSamples = Number.isFinite(previousSampledAt)
      && Number.isFinite(currentSampledAt)
      && previousResetAt > previousSampledAt
      && previousResetAt <= currentSampledAt;
    if (
      Number.isFinite(previousResetAt)
      && (
        resetOccurredBetweenSamples
        || (Number.isFinite(currentResetAt) && resetTimestampChanged && quotaJumped)
      )
    ) {
      resetBoundaryPairs.add(`${index - 1}:${index}`);
    }
  }
  const quotaCurve = smoothQuotaCurve(
    points.map(({ x, timestamp, quotaY }) => ({ x, y: quotaY, timestamp })),
    resetBoundaryPairs,
    timestampRange,
    minTimestamp,
    plotWidth,
  );
  const quotaPath = quotaCurvePath(quotaCurve);
  const durationPath = linearPath(points.map(({ x, durationY }) => ({ x, y: durationY })));
  const creditsPath = linearPath(
    points
      .filter(({ creditsY }) => creditsY !== null)
      .map(({ x, creditsY }) => ({ x, y: creditsY as number })),
  );
  // Screen y grows as quota falls, so this is -d(remaining percent)/d(hours).
  const consumptionCurve = codexConsumptionCurve(
    quotaCurve,
    hasValidTimestamps && timestampRange > 0
      ? (axisRange / plotHeight) * (plotWidth / timestampRange) * 3600000
      : 0,
  );
  const xForTimestamp = (timestamp: number) => (
    left + ((timestamp - minTimestamp) / timestampRange) * plotWidth
  );
  const consumptionBars = codexConsumptionBars(
    consumptionCurve,
    consumptionTimeDomain ? xForTimestamp(consumptionTimeDomain.start) : left,
    consumptionTimeDomain ? xForTimestamp(consumptionTimeDomain.end) : width - right,
    consumptionTimeDomain?.count ?? CONSUMPTION_BAR_TARGET,
  );
  const latestRate = consumptionCurve.latestRate === null
    ? null
    : Math.max(0, consumptionCurve.latestRate);
  const maxRate = Math.max(0, ...consumptionBars.map((bar) => bar.rate));
  const latestRateText = latestRate === null ? "—" : `${consumptionRateFormat.format(latestRate)} 百分点/小时`;
  const rateRange = maxRate || 1;
  const rateStepBase = 10 ** Math.floor(Math.log10(rateRange / RATE_LIMIT_AXIS_INTERVALS));
  const rateStep = ([1, 2, 5, 10].find((step) => step * rateStepBase * RATE_LIMIT_AXIS_INTERVALS >= rateRange) ?? 10) * rateStepBase;
  const rateAxisMin = 0;
  const rateAxisMax = Math.max(rateAxisMin + rateStep * RATE_LIMIT_AXIS_INTERVALS, Math.ceil(maxRate / rateStep) * rateStep);
  const yForRate = (rate: number) => top + (rateAxisMax - rate) / (rateAxisMax - rateAxisMin) * plotHeight;
  const showCredits = secondaryMetric === "credits" && creditsBounds !== null;
  const showConsumption = secondaryMetric === "consumption";
  const secondaryClass = showCredits ? "credits" : showConsumption ? "consumption" : "duration";
  const secondaryLabel = showCredits ? "Credits" : showConsumption ? "消耗速度" : "剩余时长";
  const secondaryAxisTicks = showCredits
    ? Array.from(
        { length: RATE_LIMIT_AXIS_INTERVALS + 1 },
        (_, index) => creditsBounds.min + ((creditsBounds.max - creditsBounds.min) * index) / RATE_LIMIT_AXIS_INTERVALS,
      )
    : null;
  const latestRemaining = remainingPercent(latest);
  const latestDurationMs = remainingDurationMs(latest);
  const latestDuration = formatRemainingDuration(latestDurationMs);
  const durationWindowDays = latest.windowMinutes / 1440;
  const durationDaysForPercent = (remaining: number) => (
    durationDaysFormat.format((remaining / 100) * durationWindowDays)
  );
  const latestCredits = creditSamples.length ? creditsValue(creditSamples.at(-1)!) : null;
  const accessibleLabel = `${label} 剩余额度与${secondaryLabel}趋势，共 ${orderedSamples.length} 个样本，当前剩余 ${formatPercentValue(latestRemaining)}，剩余时长 ${latestDuration}，剩余 Credits ${formatCreditsValue(latestCredits)}，最近消耗 ${latestRateText}`;
  const pace = quotaPace(latest, latestRate);
  const plotBottom = top + plotHeight;
  const quotaAreaPath = quotaPath && quotaCurve.length
    ? `${quotaPath} L ${quotaCurve.at(-1)!.end.x} ${plotBottom} L ${quotaCurve[0].start.x} ${plotBottom} Z`
    : "";
  const hovered = hoverIndex === null ? null : orderedSamples[hoverIndex] ?? null;
  const hoveredPoint = hoverIndex === null ? null : points[hoverIndex] ?? null;
  const hoveredCredits = hovered ? creditsValue(hovered) : null;
  // Name the source machine only once the curve merges imported samples.
  const showSampleOrigin = orderedSamples.some((sample) => sample.origin);
  const handlePointerMove = (event: PointerEvent<SVGSVGElement>) => {
    if (points.length < 2) return;
    const rect = event.currentTarget.getBoundingClientRect();
    if (!rect.width) return;
    const x = ((event.clientX - rect.left) / rect.width) * width;
    let nearest = 0;
    for (let index = 1; index < points.length; index += 1) {
      if (Math.abs(points[index].x - x) < Math.abs(points[nearest].x - x)) nearest = index;
    }
    setHoverIndex(nearest);
  };

  return (
    <article className="codex-usage-rate-limit-group">
      <header className="codex-usage-bucket-header">
        <div className="codex-usage-bucket-title">
          <h4>{label}</h4>
          <span className="codex-usage-badge">{formatWindow(latest.windowMinutes)}窗口</span>
        </div>
        <span className="codex-usage-pace" data-tone={pace.tone} title={pace.hint}>
          <span className="codex-usage-pace-dot" aria-hidden="true" />
          {pace.label}
        </span>
      </header>

      <div className="codex-usage-bucket-overview">
        <div className="codex-usage-bucket-hero">
          <strong className="codex-usage-bucket-hero-value">{formatPercentValue(latestRemaining)}</strong>
          <span>当前剩余</span>
        </div>
        <div className="codex-usage-meter" aria-hidden="true">
          <div className="codex-usage-meter-track" data-tone={pace.tone}>
            <span className="codex-usage-meter-fill" style={{ width: `${latestRemaining}%` }} />
            {pace.timePercent !== null ? (
              <span className="codex-usage-meter-marker" style={{ left: `${pace.timePercent}%` }} />
            ) : null}
          </div>
          <div className="codex-usage-meter-legend">
            <span><i className="codex-usage-swatch-quota" />额度 {formatPercentValue(latestRemaining)}</span>
            {pace.timePercent !== null ? (
              <span><i className="codex-usage-swatch-time" />时间 {formatPercentValue(pace.timePercent)}</span>
            ) : null}
          </div>
        </div>
      </div>

      <dl className="codex-usage-bucket-stats" aria-label="最新限额样本摘要">
        <div>
          <dt>剩余时长</dt>
          <dd>{latestDuration}</dd>
        </div>
        <div>
          <dt>重置时间</dt>
          <dd title={formatServerLocalTime(latest.resetsAt)}>{formatAxisTime(latest.resetsAt)}</dd>
        </div>
        <div>
          <dt>最近消耗</dt>
          <dd title={latestRate === null
            ? "当前曲线末端无法计算消耗速度"
            : `${formatServerLocalTime(latest.sampledAt)} 的平滑额度曲线消耗速度`}>
            {latestRate === null ? "—" : `${consumptionRateFormat.format(latestRate)} %/时`}
          </dd>
        </div>
        <div>
          <dt>预计耗尽</dt>
          <dd>{pace.exhaustText}</dd>
        </div>
        {latestCredits !== null ? (
          <div>
            <dt>Credits</dt>
            <dd>{formatCreditsValue(latestCredits)}</dd>
          </div>
        ) : null}
      </dl>

      <div className="codex-usage-rate-limit-chart">
        <div className="codex-usage-rate-limit-plot" ref={chartWidth.ref}>
          <svg
            viewBox={`0 0 ${width} ${height}`}
            role="img"
            aria-label={accessibleLabel}
            onPointerMove={handlePointerMove}
            onPointerLeave={() => setHoverIndex(null)}
          >
            <title>{label} 剩余额度与{secondaryLabel}趋势</title>
            <desc>
              {showCredits
                ? `按采样时间展示该额度桶的剩余额度与 Credits；右轴为剩余 Credits，从 ${formatCreditsValue(creditsBounds.min)} 到 ${formatCreditsValue(creditsBounds.max)}。`
                : showConsumption
                ? `左轴为剩余额度，右轴为消耗速度（百分点/小时），从 ${consumptionRateFormat.format(rateAxisMin)} 到 ${consumptionRateFormat.format(rateAxisMax)}；柱高为固定时间区间内平滑额度曲线负导数的平均值，随横轴范围变化；重置间隔为过渡估计，数据不足处留空。`
                : `按采样时间展示该额度桶的剩余额度与剩余时长；左右纵轴按当前数据范围同步缩放，左轴为${formatPercentValue(axisBounds.min)}到${formatPercentValue(axisBounds.max)}，右轴为${durationDaysForPercent(axisBounds.min)}天到${durationDaysForPercent(axisBounds.max)}天。`}
            </desc>
            <defs>
              <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" className="codex-usage-rate-limit-area-stop-top" />
                <stop offset="100%" className="codex-usage-rate-limit-area-stop-bottom" />
              </linearGradient>
            </defs>
            <text
              className="codex-usage-rate-limit-quota-axis-title"
              x={left}
              y={16}
              textAnchor="start"
            >
              剩余额度
            </text>
            <text
              className={`codex-usage-rate-limit-${secondaryClass}-axis-title`}
              x={width - right}
              y={16}
              textAnchor="end"
            >
              {showCredits ? "Credits" : showConsumption ? "消耗速度（百分点/小时）" : "剩余时长"}
            </text>
            {axisTicks.map((remaining, index) => {
              const y = yForPercent(remaining);
              return (
                <g key={remaining} className="codex-usage-rate-limit-grid">
                  <line x1={left} x2={width - right} y1={y} y2={y} />
                  <text
                    className="codex-usage-rate-limit-quota-tick"
                    x={left - 8}
                    y={y + 4}
                    textAnchor="end"
                  >
                    {remaining}%
                  </text>
                  <text
                    className={`codex-usage-rate-limit-${secondaryClass}-tick`}
                    x={width - right + 8}
                    y={y + 4}
                    textAnchor="start"
                  >
                    {showConsumption
                      ? consumptionRateFormat.format(rateAxisMin + index * (rateAxisMax - rateAxisMin) / RATE_LIMIT_AXIS_INTERVALS)
                      : showCredits
                        ? formatCreditsValue(secondaryAxisTicks?.[index] ?? null)
                      : `${durationDaysForPercent(remaining)} 天`}
                  </text>
                </g>
              );
            })}
            {points.length > 1 ? (
              <>
                {quotaAreaPath ? (
                  <path className="codex-usage-rate-limit-area" d={quotaAreaPath} fill={`url(#${gradientId})`} />
                ) : null}
                {showConsumption ? consumptionBars.map((bar) => {
                  const visibleStart = Math.max(left, bar.start);
                  const visibleEnd = Math.min(width - right, bar.end);
                  return (
                    <rect
                      key={bar.start}
                      className="codex-usage-rate-limit-consumption-bar"
                      x={visibleStart + (visibleEnd - visibleStart) * 0.15}
                      y={Math.min(yForRate(0), yForRate(bar.rate))}
                      width={(visibleEnd - visibleStart) * 0.7}
                      height={Math.abs(yForRate(0) - yForRate(bar.rate))}
                      rx={1.5}
                    >
                      <title>{`${formatConsumptionPeriod(
                        bar.start,
                        bar.end,
                        minTimestamp,
                        timestampRange,
                        left,
                        plotWidth,
                        orderedSamples,
                      )}，${consumptionRateFormat.format(bar.rate)}%每小时`}</title>
                    </rect>
                  );
                }) : showCredits
                  ? <path className="codex-usage-rate-limit-credits-line" d={creditsPath} />
                  : <path className="codex-usage-rate-limit-duration-line" d={durationPath} />}
                <path className="codex-usage-rate-limit-line" d={quotaPath} />
                {hoveredPoint ? (
                  <g className="codex-usage-rate-limit-hover" aria-hidden="true">
                    <line x1={hoveredPoint.x} x2={hoveredPoint.x} y1={top} y2={plotBottom} />
                    {!showConsumption && !(showCredits && hoveredPoint.creditsY === null) ? (
                      <circle
                        className="codex-usage-rate-limit-hover-secondary"
                        cx={hoveredPoint.x}
                        cy={showCredits ? hoveredPoint.creditsY as number : hoveredPoint.durationY}
                        r={4}
                      />
                    ) : null}
                    <circle className="codex-usage-rate-limit-hover-quota" cx={hoveredPoint.x} cy={hoveredPoint.quotaY} r={4.5} />
                  </g>
                ) : null}
              </>
            ) : null}
            <text className="codex-usage-rate-limit-axis-label" x={left} y={height - 8} textAnchor="start">
              {formatAxisTime(orderedSamples[0].sampledAt)}
            </text>
            {orderedSamples.length > 1 ? (
              <text className="codex-usage-rate-limit-axis-label" x={width - right} y={height - 8} textAnchor="end">
                {formatAxisTime(latest.sampledAt)}
              </text>
            ) : null}
          </svg>
          {hovered && hoveredPoint ? (
            <div
              className="codex-usage-rate-limit-tooltip"
              data-align={hoveredPoint.x > width * 0.62 ? "end" : "start"}
              style={{
                left: `${(hoveredPoint.x / width) * 100}%`,
                top: `${(Math.max(top, Math.min(hoveredPoint.quotaY, plotBottom - 40)) / height) * 100}%`,
              }}
              aria-hidden="true"
            >
              <time>{formatServerLocalTime(hovered.sampledAt)}</time>
              <span><i className="codex-usage-swatch-quota" />剩余额度 <b>{formatPercentValue(remainingPercent(hovered))}</b></span>
              <span><i className="codex-usage-swatch-time" />剩余时长 <b>{formatRemainingDuration(remainingDurationMs(hovered))}</b></span>
              {hoveredCredits !== null && hovered.windowMinutes === WEEKLY_WINDOW_MINUTES ? (
                <span><i className="codex-usage-swatch-time" />Credits <b>{formatCreditsValue(hoveredCredits)}</b></span>
              ) : null}
              {showSampleOrigin ? (
                <span className="codex-usage-rate-limit-tooltip-origin">来源 <b>{hovered.origin || "本机"}</b></span>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
      {showConsumption ? (
        <p className="codex-usage-rate-limit-note">
          {consumptionBars.length
            ? "柱高表示固定时间区间内的消耗速度；重置间隔为过渡估计。"
            : "暂无可计算的消耗速度，需要有效时间范围内的连续额度曲线。"}
        </p>
      ) : null}
    </article>
  );
}

function CodexRateLimitChart({
  samples,
  providerName,
}: {
  samples: CodexRateLimitSample[];
  providerName: UsagePanelProvider;
}) {
  const [secondaryMetric, setSecondaryMetric] = useState<RateLimitSecondaryMetric>("duration");
  const displayName = providerName === "claude" ? "Claude" : "Codex";
  const generalLimitId = providerName === "claude"
    ? GENERAL_CLAUDE_RATE_LIMIT_ID
    : GENERAL_CODEX_RATE_LIMIT_ID;
  const hasWeeklyCredits = samples.some((sample) => (
    sample.limitId === generalLimitId
    && sample.windowMinutes === WEEKLY_WINDOW_MINUTES
    && creditsValue(sample) !== null
  ));
  const activeSecondaryMetric = secondaryMetric === "credits" && !hasWeeklyCredits
    ? "duration"
    : secondaryMetric;
  const limitGroups = useMemo(() => {
    const grouped = new Map<string, {
      limitId: string;
      planType: string | null;
      samples: CodexRateLimitSample[];
    }>();
    const visibleSamples = samples.filter((sample) => (
      providerName === "claude"
        || (
          sample.limitId !== GPT_RESERVE_RATE_LIMIT_ID
          && sample.limitId !== SECONDARY_CODEX_RATE_LIMIT_ID
        )
    ));
    const knownPlanTypesByLimitId = new Map<string, Set<string>>();
    for (const sample of visibleSamples) {
      const planType = sample.planType?.trim().toLowerCase();
      if (!planType) continue;
      const knownPlanTypes = knownPlanTypesByLimitId.get(sample.limitId) || new Set<string>();
      knownPlanTypes.add(planType);
      knownPlanTypesByLimitId.set(sample.limitId, knownPlanTypes);
    }
    for (const sample of visibleSamples) {
      let planType = sample.planType?.trim().toLowerCase() || null;
      if (!planType) {
        const knownPlanTypes = knownPlanTypesByLimitId.get(sample.limitId);
        if (knownPlanTypes?.size === 1) {
          planType = [...knownPlanTypes][0];
        }
      }
      const key = `${sample.limitId}\u0000${planType || ""}`;
      const group = grouped.get(key) || { limitId: sample.limitId, planType, samples: [] };
      group.samples.push(sample);
      grouped.set(key, group);
    }
    const groups = Array.from(grouped.values());
    const limitIds = [
      generalLimitId,
      ...visibleSamples
        .map((sample) => sample.limitId)
        .filter((limitId) => (
          limitId !== generalLimitId
        )),
    ];
    return [...new Set(limitIds)].flatMap((limitId) => {
      const matches = groups.filter((group) => group.limitId === limitId);
      return matches.length ? matches : [{ limitId, planType: null, samples: [] }];
    });
  }, [generalLimitId, providerName, samples]);

  const limitLabel = (limitId: string) => {
    if (limitId === generalLimitId) return `通用 ${displayName}`;
    if (limitId === CLAUDE_OVERAGE_RATE_LIMIT_ID) return "Claude 含超额用量";
    if (providerName === "claude") return limitId;
    if (limitId === SECONDARY_CODEX_RATE_LIMIT_ID) return "gpt-5.3-codex-spark";
    return limitId;
  };

  return (
    <section className="codex-usage-section" aria-labelledby={`${providerName}-rate-limit-title`}>
      <div className="codex-usage-section-heading">
        <div className="codex-usage-chart-title">
          <h3 id={`${providerName}-rate-limit-title`}>{displayName} 剩余额度趋势</h3>
          <div className="codex-usage-chart-legend" aria-hidden="true">
            <span><i className="codex-usage-swatch-quota" />剩余额度</span>
            <span>
              <i className={activeSecondaryMetric === "duration" ? "codex-usage-swatch-time codex-usage-swatch-dashed" : "codex-usage-swatch-time"} />
              {activeSecondaryMetric === "credits" ? "Credits" : activeSecondaryMetric === "consumption" ? "消耗速度" : "剩余时长"}
            </span>
          </div>
        </div>
        <div className="codex-usage-chart-controls" role="group" aria-label="图表右轴">
          <span>右轴</span>
          <div className="codex-usage-chart-toggle">
            {(["duration", "consumption"] as const).map((metric) => (
              <button
                key={metric}
                type="button"
                aria-pressed={secondaryMetric === metric}
                onClick={() => setSecondaryMetric(metric)}
              >
                {metric === "duration" ? "剩余时长" : "消耗速度"}
              </button>
            ))}
            {hasWeeklyCredits ? (
              <button
                type="button"
                aria-pressed={secondaryMetric === "credits"}
                onClick={() => setSecondaryMetric("credits")}
              >
                Credits
              </button>
            ) : null}
          </div>
        </div>
      </div>
      <div className="codex-usage-rate-limit-groups">
        {limitGroups.map(({ limitId, planType, samples: limitSamples }) => (
          <CodexRateLimitBucketChart
            key={`${limitId}:${planType || "empty"}`}
            label={limitSamples.length ? `${limitLabel(limitId)} · ${formatPlanType(planType)}` : limitLabel(limitId)}
            samples={limitSamples}
            secondaryMetric={activeSecondaryMetric}
            providerName={displayName}
          />
        ))}
      </div>
    </section>
  );
}

// Keyed by provider and refresh generation, so each switch starts from a clean
// state and late responses for the previous provider land on an unmounted view.
function ProviderUsageView({ client, provider, onTimeBasisChange }: ProviderUsageViewProps) {
  const displayName = USAGE_PROVIDER_LABELS[provider];
  const [config, setConfig] = useState<CodexUsageConfig | null>(null);
  const [stats, setStats] = useState<CodexUsageStats | null>(null);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [loading, setLoading] = useState(true);
  const [querying, setQuerying] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [quickRange, setQuickRange] = useState<QuickRangeKey | "custom">(DEFAULT_QUICK_RANGE);
  const queryRequestIdRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const requestId = ++queryRequestIdRef.current;

    const load = async () => {
      setLoading(true);
      setError("");
      setNotice("");
      try {
        const nextConfig = provider === "claude"
          ? await client.getClaudeUsageConfig()
          : await client.getCodexUsageConfig();
        if (cancelled || requestId !== queryRequestIdRef.current) return;
        const range = defaultRange(nextConfig.timeBasis.today);
        setConfig(nextConfig);
        setStartDate(range.startDate);
        setEndDate(range.endDate);

        const nextStats = provider === "claude"
          ? await client.getClaudeUsageStats(range)
          : await client.getCodexUsageStats(range);
        if (cancelled || requestId !== queryRequestIdRef.current) return;
        setStats(nextStats);
      } catch (nextError) {
        if (!cancelled && requestId === queryRequestIdRef.current) {
          setError(getErrorMessage(nextError, `加载 ${displayName} 额度失败`));
        }
      } finally {
        if (!cancelled && requestId === queryRequestIdRef.current) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [client, displayName, provider]);

  const utcOffset = config?.timeBasis.utcOffset || stats?.timeBasis.utcOffset || "";
  useEffect(() => {
    if (utcOffset) onTimeBasisChange(utcOffset);
  }, [onTimeBasisChange, utcOffset]);

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
      const query = {
        startDate: normalizedStartDate,
        endDate: normalizedEndDate,
      };
      const nextStats = provider === "claude"
        ? await client.getClaudeUsageStats(query)
        : await client.getCodexUsageStats(query);
      if (requestId === queryRequestIdRef.current) {
        setStats(nextStats);
      }
    } catch (nextError) {
      if (requestId === queryRequestIdRef.current) {
        setError(getErrorMessage(nextError, `查询 ${displayName} 额度失败`));
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
      const nextConfig = provider === "claude"
        ? await client.updateClaudeUsageConfig({ enabled })
        : await client.updateCodexUsageConfig({ enabled });
      setConfig(nextConfig);
      setStats((current) => current ? { ...current, enabled: nextConfig.enabled } : current);
      setNotice(enabled
        ? `${displayName} 额度采集已开启。`
        : `${displayName} 额度采集已关闭，历史额度仍可查询。`);
    } catch (nextError) {
      setError(`保存 ${displayName} 额度采集设置失败：${getErrorMessage(nextError, "请稍后重试")}`);
    } finally {
      setSaving(false);
    }
  };

  const applyQuickRange = (key: QuickRangeKey, days: number | null) => {
    setQuickRange(key);
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
    setQuickRange(DEFAULT_QUICK_RANGE);
    const range = defaultRange(config?.timeBasis.today || stats?.timeBasis.today || "");
    setStartDate(range.startDate);
    setEndDate(range.endDate);
    void runStatsQuery(range.startDate, range.endDate);
  };

  const hasRateLimitSamples = Boolean(stats?.rateLimitSamples.length);

  return (
    <>
      {error ? <div role="alert" className="codex-usage-alert codex-usage-alert-error">{error}</div> : null}
      {notice ? <div role="status" className="codex-usage-alert codex-usage-alert-success">{notice}</div> : null}

      {loading ? <p role="status" className="codex-usage-loading">正在加载 {displayName} 额度…</p> : null}

      {!loading && config ? (
        <>
          <section className="codex-usage-section codex-usage-toolbar" aria-labelledby={`${provider}-usage-toolbar-title`}>
            <h3 id={`${provider}-usage-toolbar-title`} className="codex-usage-visually-hidden">采集与筛选</h3>
            <div className="codex-usage-toolbar-row">
              <dl className="codex-usage-provider-details" aria-label="当前 Provider">
                <div>
                  <dt>Provider</dt>
                  <dd>{providerLabel(config.currentProvider)}</dd>
                </div>
                <div className="codex-usage-provider-url">
                  <dt>规范化地址</dt>
                  <dd className="codex-usage-breakable" title={config.currentProvider.baseUrl || undefined}>
                    {config.currentProvider.baseUrl || `${displayName} 官方`}
                  </dd>
                </div>
                <div>
                  <dt>解析状态</dt>
                  <dd>
                    <span
                      className="codex-usage-status-dot"
                      data-tone={config.currentProvider.resolution === "resolved"
                        ? "good"
                        : config.currentProvider.resolution ? "warning" : "neutral"}
                      aria-hidden="true"
                    />
                    {config.currentProvider.resolution
                      ? providerResolutionLabels[config.currentProvider.resolution]
                      : "未知/未提供"}
                  </dd>
                </div>
              </dl>
              <label className="codex-usage-switch">
                <span>{config.enabled ? "采集中" : "采集已关闭"}</span>
                <input
                  aria-label={`启用 ${displayName} 额度采集`}
                  type="checkbox"
                  checked={config.enabled}
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
                void runStatsQuery();
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
                <button type="button" onClick={resetFilters} disabled={querying}>重置</button>
              </div>
            </form>
            {!config.enabled && hasRateLimitSamples ? (
              <p className="codex-usage-disabled-history">额度采集已关闭，历史额度仍可查询。</p>
            ) : null}
          </section>

          {stats ? (
            <>
              <CodexRateLimitChart samples={stats.rateLimitSamples} providerName={provider} />
              {!hasRateLimitSamples ? <p className="codex-usage-empty">暂无符合筛选条件的 {displayName} 额度数据。</p> : null}
            </>
          ) : null}
        </>
      ) : null}
    </>
  );
}

export function UsagePanel({ client, provider, onProviderChange, refreshKey = 0 }: UsagePanelProps) {
  // The server-local offset is shared by both providers, so keep the last one
  // visible while the next provider view loads.
  const [utcOffset, setUtcOffset] = useState("");
  // Sample files cover both providers, so transfers live above the tabs and
  // reload the visible view only when its data changed.
  const [transferAction, setTransferAction] = useState<"export" | "import" | "delete" | null>(null);
  const [transferNotice, setTransferNotice] = useState("");
  const [transferError, setTransferError] = useState("");
  const [samplesRevision, setSamplesRevision] = useState(0);
  const importInputRef = useRef<HTMLInputElement>(null);

  const runTransfer = async (
    action: "export" | "import" | "delete",
    run: () => Promise<{ notice: string; changed: boolean }>,
    failure: string,
  ) => {
    setTransferAction(action);
    setTransferNotice("");
    setTransferError("");
    try {
      const { notice, changed } = await run();
      setTransferNotice(notice);
      if (changed) setSamplesRevision((current) => current + 1);
    } catch (nextError) {
      setTransferError(getErrorMessage(nextError, failure));
    } finally {
      setTransferAction(null);
    }
  };

  const exportSamples = () => runTransfer("export", async () => {
    const result = await client.exportUsageSamples();
    return {
      notice: `已导出 ${numberFormat.format(result.sampleCount)} 条额度样本：${result.filename}`,
      changed: false,
    };
  }, "导出额度样本失败");

  const importSamples = (file: File) => runTransfer("import", async () => {
    const result = await client.importUsageSamples(file);
    return { notice: formatImportNotice(result), changed: result.inserted > 0 };
  }, "导入额度样本失败");

  const deleteImportedSamples = () => {
    if (!window.confirm("移除所有从其他设备导入的额度样本？本机采集的样本不受影响。")) return;
    void runTransfer("delete", async () => {
      const { deleted } = await client.deleteImportedUsageSamples();
      return {
        notice: deleted
          ? `已移除 ${numberFormat.format(deleted)} 条导入的额度样本。`
          : "没有从其他设备导入的额度样本。",
        changed: deleted > 0,
      };
    }, "移除导入的额度样本失败");
  };

  const handleProviderTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const lastIndex = USAGE_PROVIDERS.length - 1;
    let nextIndex: number;
    if (event.key === "ArrowRight") nextIndex = index === lastIndex ? 0 : index + 1;
    else if (event.key === "ArrowLeft") nextIndex = index === 0 ? lastIndex : index - 1;
    else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = lastIndex;
    else return;
    event.preventDefault();
    event.currentTarget.parentElement
      ?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[nextIndex]
      ?.focus();
    onProviderChange(USAGE_PROVIDERS[nextIndex]);
  };

  return (
    <section aria-labelledby="usage-title" className="codex-usage-panel">
      <div className="codex-usage-heading">
        <div className="codex-usage-title-group">
          <h2 id="usage-title">Usage</h2>
          <div role="tablist" aria-label="Usage 来源" className="codex-usage-provider-tabs">
            {USAGE_PROVIDERS.map((id, index) => {
              const selected = id === provider;
              return (
                <button
                  key={id}
                  id={`usage-provider-tab-${id}`}
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  aria-controls={selected ? "usage-provider-panel" : undefined}
                  tabIndex={selected ? 0 : -1}
                  className={selected ? "tcb-selected-accent" : undefined}
                  onClick={() => onProviderChange(id)}
                  onKeyDown={(event) => handleProviderTabKeyDown(event, index)}
                >
                  {USAGE_PROVIDER_LABELS[id]}
                </button>
              );
            })}
          </div>
        </div>
        <div className="codex-usage-heading-actions">
          <div className="codex-usage-transfer" role="group" aria-label="多设备额度样本">
            <button
              type="button"
              disabled={transferAction !== null}
              title="导出本机全部 Codex 与 Claude 额度样本，在其他设备导入后合并为同一条曲线"
              onClick={() => void exportSamples()}
            >
              {transferAction === "export" ? "导出中…" : "导出样本"}
            </button>
            <button
              type="button"
              disabled={transferAction !== null}
              title="导入其他设备导出的额度样本；已有样本会自动跳过"
              onClick={() => importInputRef.current?.click()}
            >
              {transferAction === "import" ? "导入中…" : "导入样本"}
            </button>
            <button
              type="button"
              disabled={transferAction !== null}
              title="移除所有从其他设备导入的额度样本，保留本机采集的样本"
              onClick={deleteImportedSamples}
            >
              {transferAction === "delete" ? "移除中…" : "移除导入"}
            </button>
            <input
              ref={importInputRef}
              type="file"
              accept="application/json,.json"
              aria-label="选择额度样本文件"
              aria-hidden="true"
              className="codex-usage-visually-hidden"
              tabIndex={-1}
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.currentTarget.value = "";
                if (file) void importSamples(file);
              }}
            />
          </div>
          <span className="codex-usage-time-basis">服务端本地时间 {utcOffset || "—"}</span>
        </div>
      </div>

      {transferError ? <div role="alert" className="codex-usage-alert codex-usage-alert-error">{transferError}</div> : null}
      {transferNotice ? <div role="status" className="codex-usage-alert codex-usage-alert-success">{transferNotice}</div> : null}

      <div
        role="tabpanel"
        id="usage-provider-panel"
        aria-labelledby={`usage-provider-tab-${provider}`}
        className="codex-usage-provider-panel"
      >
        <ProviderUsageView
          key={`${provider}:${refreshKey}:${samplesRevision}`}
          client={client}
          provider={provider}
          onTimeBasisChange={setUtcOffset}
        />
      </div>
    </section>
  );
}
