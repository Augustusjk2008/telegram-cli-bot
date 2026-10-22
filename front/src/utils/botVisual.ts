import type { CSSProperties } from "react";

const BOT_ACCENT_COLORS = [
  "var(--identity-bot1)",
  "var(--identity-bot2)",
  "var(--identity-bot3)",
  "var(--identity-bot4)",
  "var(--identity-bot5)",
  "var(--identity-bot6)",
  "var(--identity-bot7)",
  "var(--identity-bot8)",
];

const BOT_IDENTITY_COLORS = {
  codex: "var(--identity-codex)",
  codexServer: "var(--identity-codex-server)",
  claude: "var(--identity-claude)",
  antigravity: "var(--identity-antigravity)",
  deepseek: "var(--identity-deepseek)",
} as const;

function hashAlias(alias: string) {
  let hash = 0;
  const normalized = alias.trim().toLowerCase() || "main";
  for (let index = 0; index < normalized.length; index += 1) {
    hash = (hash * 31 + normalized.charCodeAt(index)) >>> 0;
  }
  return hash;
}

export function getBotAccentColor(alias: string) {
  return BOT_ACCENT_COLORS[hashAlias(alias) % BOT_ACCENT_COLORS.length];
}

export function getBotAccentStyle(alias: string): CSSProperties {
  return {
    backgroundColor: getBotAccentColor(alias),
  };
}

function identityKey(cliType: string | undefined) {
  if (cliType === "claude") return "claude" as const;
  if (cliType === "antigravity") return "antigravity" as const;
  if (cliType === "deepseek") return "deepseek" as const;
  if (cliType === "codex_server") return "codexServer" as const;
  return "codex" as const;
}

export function getBotIdentityTextStyle(cliType: string | undefined): CSSProperties {
  const identity = BOT_IDENTITY_COLORS[identityKey(cliType)];
  return {
    color: identity,
  };
}
