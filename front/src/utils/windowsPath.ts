export function normalizeWindowsPathInput(value: string): string {
  const trimmed = value.trim();
  if (!trimmed.includes("\\")) {
    return trimmed;
  }

  if (trimmed.startsWith("\\\\")) {
    return `\\\\${trimmed.slice(2).replace(/\\{2,}/g, "\\")}`;
  }

  return trimmed.replace(/\\{2,}/g, "\\");
}
