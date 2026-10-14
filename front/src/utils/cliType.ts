export function defaultCliPathForType(cliType: string) {
  if (cliType === "claude") return "claude";
  if (cliType === "antigravity") return "agy";
  return "codex";
}

export function cliTypeLabel(cliType: string) {
  if (cliType === "codex_server") return "codex server";
  if (cliType === "antigravity") return "Antigravity CLI";
  return cliType;
}

export function isCodexCli(cliType: string | undefined) {
  const normalized = cliType?.trim().toLowerCase();
  return normalized === "codex" || normalized === "codex_server";
}
