export function defaultCliPathForType(cliType: string) {
  return cliType === "claude" ? "claude" : "codex";
}

export function cliTypeLabel(cliType: string) {
  return cliType === "codex_server" ? "codex server" : cliType;
}

export function isCodexCli(cliType: string | undefined) {
  const normalized = cliType?.trim().toLowerCase();
  return normalized === "codex" || normalized === "codex_server";
}
