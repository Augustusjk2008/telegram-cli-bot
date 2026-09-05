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
  return { segments, minRate, maxRate, latestRate: segments.at(-1)?.end.y ?? null };
}
