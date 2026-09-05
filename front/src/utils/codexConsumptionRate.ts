import type { CodexRateLimitSample } from "../services/types";

const HOUR_MS = 60 * 60 * 1000;

/** Percentage points per hour over each adjacent, chronologically ordered pair. */
export function codexConsumptionRates(samples: CodexRateLimitSample[]): (number | null)[] {
  const conflictingTimes = new Set<number>();
  samples.forEach((current, index) => {
    const next = samples[index + 1];
    const timestamp = Date.parse(current.sampledAt);
    if (next && timestamp === Date.parse(next.sampledAt) && (
      current.usedPercent !== next.usedPercent
      || Date.parse(current.resetsAt) !== Date.parse(next.resetsAt)
      || current.windowMinutes !== next.windowMinutes
    )) conflictingTimes.add(timestamp);
  });

  return samples.map((current, index) => {
    const previous = samples[index - 1];
    if (!previous) return null;
    const start = Date.parse(previous.sampledAt);
    const end = Date.parse(current.sampledAt);
    const previousReset = Date.parse(previous.resetsAt);
    const currentReset = Date.parse(current.resetsAt);
    if (
      ![start, end, previousReset, currentReset].every(Number.isFinite)
      || end <= start
      || conflictingTimes.has(start)
      || conflictingTimes.has(end)
      || previousReset !== currentReset
      || start >= previousReset
      || end >= currentReset
      || previous.windowMinutes !== current.windowMinutes
      || previous.limitId !== current.limitId
      || previous.planType?.trim().toLowerCase() !== current.planType?.trim().toLowerCase()
      || ![previous.usedPercent, current.usedPercent].every((value) => (
        Number.isFinite(value) && value >= 0 && value <= 100
      ))
      || current.usedPercent < previous.usedPercent
    ) return null;

    const rate = (current.usedPercent - previous.usedPercent) * HOUR_MS / (end - start);
    return Number.isFinite(rate) ? rate : null;
  });
}
