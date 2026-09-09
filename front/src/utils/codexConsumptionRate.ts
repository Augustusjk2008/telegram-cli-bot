type CurvePoint = { x: number; y: number };

export type QuotaCurveSegment = {
  start: CurvePoint;
  end: CurvePoint;
  // Cubic y controls; x controls are at one third and two thirds of the span.
  controls?: [number, number];
  reset?: boolean;
};

type ConsumptionCurveSegment = {
  start: CurvePoint;
  control: CurvePoint;
  end: CurvePoint;
};

type ConsumptionResetBridge = {
  start: CurvePoint;
  controls: [CurvePoint, CurvePoint];
  end: CurvePoint;
};

function bridgeConsumptionResets(quota: QuotaCurveSegment[], segments: (ConsumptionCurveSegment | null)[]) {
  const bridges = new Map<number, ConsumptionResetBridge>();
  let previousIndex = -1;
  segments.forEach((next, index) => {
    if (!next) return;
    const previous = segments[previousIndex];
    const gap = quota.slice(previousIndex + 1, index);
    if (previous && gap.length && gap.every((segment, gapIndex) => (
      segment.reset
      && Number.isFinite(segment.start.x) && Number.isFinite(segment.end.x)
      && segment.end.x > segment.start.x
      && segment.start.x === (gapIndex ? gap[gapIndex - 1].end.x : previous.end.x)
    )) && gap.at(-1)?.end.x === next.start.x) {
      const start = previous.end;
      const end = next.start;
      const width = end.x - start.x;
      const delta = end.y - start.y;
      const incomingSlope = 2 * (previous.end.y - previous.control.y) / (previous.end.x - previous.start.x);
      const outgoingSlope = 2 * (next.control.y - next.start.y) / (next.end.x - next.start.x);
      const limitTangent = (slope: number) => delta === 0 ? 0 : Math.min(1, Math.max(0, slope * width / (3 * delta)));
      const incoming = limitTangent(incomingSlope);
      const outgoing = limitTangent(outgoingSlope);
      // Controls stay within the endpoint range: no invented spike at a refill.
      // Preserve the neighbouring tangents wherever that monotonicity allows it.
      bridges.set(index, {
        start,
        controls: [
          { x: start.x + width / 3, y: start.y + delta * incoming },
          { x: end.x - width / 3, y: end.y - delta * outgoing },
        ],
        end,
      });
    }
    previousIndex = index;
  });
  return bridges;
}

/** Differentiate the displayed quota geometry, converting screen slope to percentage points/hour. */
export function codexConsumptionCurve(quota: QuotaCurveSegment[], unitsPerSlope: number) {
  let minRate = 0;
  let maxRate = 0;
  const segments = quota.map((segment): ConsumptionCurveSegment | null => {
    const { start, end, controls, reset } = segment;
    const width = end.x - start.x;
    if (reset || width <= 0 || !Number.isFinite(unitsPerSlope) || unitsPerSlope <= 0) return null;
    const slope = (end.y - start.y) / width;
    const rates = controls
      ? [controls[0] - start.y, controls[1] - controls[0], end.y - controls[1]]
        .map((delta) => 3 * delta / width * unitsPerSlope)
      : [slope, slope, slope].map((value) => value * unitsPerSlope);
    if (![start.x, end.x, ...rates].every(Number.isFinite)) return null;
    const [first, control, last] = rates;
    const extrema = [first, last];
    const denominator = first - 2 * control + last;
    const t = denominator === 0 ? -1 : (first - control) / denominator;
    if (t > 0 && t < 1) {
      extrema.push((1 - t) ** 2 * first + 2 * (1 - t) * t * control + t ** 2 * last);
    }
    minRate = Math.min(minRate, ...extrema);
    maxRate = Math.max(maxRate, ...extrema);
    return {
      start: { x: start.x, y: first },
      control: { x: (start.x + end.x) / 2, y: control },
      end: { x: end.x, y: last },
    };
  });
  return {
    segments,
    resetBridges: bridgeConsumptionResets(quota, segments),
    minRate,
    maxRate,
    latestRate: segments.at(-1)?.end.y ?? null,
  };
}

/** Equal time bins, averaged over the derivative curve and its reset transitions. */
export function codexConsumptionBars(
  curve: ReturnType<typeof codexConsumptionCurve>,
  startX: number,
  endX: number,
  count = 32,
) {
  const bars: { start: number; end: number; rate: number }[] = [];
  if (!Number.isFinite(startX) || !Number.isFinite(endX) || endX <= startX || !Number.isInteger(count) || count <= 0) return bars;
  const segments = [
    ...curve.segments.filter((segment): segment is ConsumptionCurveSegment => segment !== null),
    ...curve.resetBridges.values(),
  ];
  if (!segments.length) return bars;
  const dataStart = Math.min(...segments.map((segment) => segment.start.x));
  const dataEnd = Math.max(...segments.map((segment) => segment.end.x));
  const valueAt = (segment: ConsumptionCurveSegment | ConsumptionResetBridge, x: number) => {
    const t = (x - segment.start.x) / (segment.end.x - segment.start.x);
    const u = 1 - t;
    return "controls" in segment
      ? u ** 3 * segment.start.y + 3 * u ** 2 * t * segment.controls[0].y
        + 3 * u * t ** 2 * segment.controls[1].y + t ** 3 * segment.end.y
      : u ** 2 * segment.start.y + 2 * u * t * segment.control.y + t ** 2 * segment.end.y;
  };
  const width = (endX - startX) / count;
  for (let index = 0; index < count; index += 1) {
    const start = startX + index * width;
    const end = startX + (index + 1) * width;
    let area = 0;
    let covered = 0;
    for (const segment of segments) {
      const left = Math.max(start, segment.start.x);
      const right = Math.min(end, segment.end.x);
      if (right <= left) continue;
      // Simpson's rule is exact for these quadratic and cubic polynomials.
      area += (right - left) / 6 * (valueAt(segment, left)
        + 4 * valueAt(segment, (left + right) / 2) + valueAt(segment, right));
      covered += right - left;
    }
    const availableWidth = Math.max(0, Math.min(end, dataEnd) - Math.max(start, dataStart));
    if (availableWidth > 0 && covered >= availableWidth * (1 - 1e-9) && Number.isFinite(area)) {
      bars.push({ start, end, rate: Math.max(0, area / covered) });
    }
  }
  return bars;
}
