export function normalizePathInput(value: string): string {
  const trimmed = value.trim();
  const backslashRuns = [...trimmed.matchAll(/\\+/g)].map((match) => match[0].length);

  if (backslashRuns.length === 0) {
    return trimmed;
  }

  const shouldCollapseRuns = backslashRuns.every((length) => length >= 2 && length % 2 === 0);
  if (!shouldCollapseRuns) {
    return trimmed;
  }

  return trimmed.replace(/\\+/g, (run) => "\\".repeat(run.length / 2));
}
