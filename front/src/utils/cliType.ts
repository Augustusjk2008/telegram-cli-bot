export function defaultCliPathForType(cliType: string) {
  if (cliType === "claude") return "claude";
  if (cliType === "antigravity") return "agy";
  if (cliType === "deepseek") return "dsh";
  return "codex";
}

export function cliPathPlaceholderForType(cliType: string) {
  if (cliType === "deepseek") return "桌面版安装目录\\resources\\runtime\\cli\\bin\\dsh.cmd";
  return defaultCliPathForType(cliType);
}

export function cliTypeLabel(cliType: string) {
  if (cliType === "codex_server") return "codex server";
  if (cliType === "antigravity") return "Antigravity CLI";
  if (cliType === "deepseek") return "DeepSeek Harness";
  return cliType;
}

export function isCodexCli(cliType: string | undefined) {
  const normalized = cliType?.trim().toLowerCase();
  return normalized === "codex" || normalized === "codex_server";
}
