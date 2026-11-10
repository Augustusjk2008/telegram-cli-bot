export function defaultCliPathForType(cliType: string) {
  if (cliType === "claude") return "claude";
  if (cliType === "antigravity") return "agy";
  if (cliType === "deepseek") return "dsh";
  return "codex";
}

type CliPathCandidate = {
  alias: string;
  cliType: string;
  cliPath?: string;
  isMain?: boolean;
};

// codex and codex server run the same executable, so either one's path fits the other.
function cliExecutableFamily(cliType: string) {
  return isCodexCli(cliType) ? ["codex", "codex_server"] : [cliType];
}

/** A configured path from agents on these CLI types: main first, explicit paths over bare default commands. */
function sharedCliPath(cliTypes: readonly string[], bots: readonly CliPathCandidate[]) {
  const defaults = new Set<string>(cliTypes.map(defaultCliPathForType));
  const candidates = bots
    .filter((bot) => cliTypes.includes(bot.cliType) && bot.cliPath?.trim())
    .sort((left, right) => Number(Boolean(right.isMain || right.alias === "main")) - Number(Boolean(left.isMain || left.alias === "main")));
  const explicit = candidates.find((bot) => !defaults.has(bot.cliPath!.trim()));
  return (explicit || candidates[0])?.cliPath?.trim() || "";
}

/**
 * Suggests the CLI path for `cliType`: the agent's own saved path when it already runs that CLI,
 * otherwise the path other agents use for it, otherwise the CLI's default command.
 */
export function suggestCliPath(cliType: string, bots: readonly CliPathCandidate[], current?: CliPathCandidate) {
  const ownPath = current?.cliPath?.trim() || "";
  if (current?.cliType === cliType && ownPath) {
    return ownPath;
  }
  const others = current ? bots.filter((bot) => bot.alias !== current.alias) : bots;
  const sameType = sharedCliPath([cliType], others);
  if (sameType) {
    return sameType;
  }
  const family = cliExecutableFamily(cliType);
  if (family.length > 1) {
    if (current && family.includes(current.cliType) && ownPath) {
      return ownPath;
    }
    const sameExecutable = sharedCliPath(family, others);
    if (sameExecutable) {
      return sameExecutable;
    }
  }
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
