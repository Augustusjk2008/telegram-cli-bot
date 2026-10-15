import type { CSSProperties } from "react";

const BOT_ACCENT_COLORS = [
  "#0891b2",
  "#2563eb",
  "#059669",
  "#ea580c",
  "#db2777",
  "#7c3aed",
  "#0d9488",
  "#65a30d",
];

const BOT_IDENTITY_COLORS = {
  codex: "#5aa7ff",
  claude: "#c79270",
  antigravity: "#6fd99a",
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
  return "codex" as const;
}

export function getBotIdentityTextStyle(cliType: string | undefined): CSSProperties {
  const identity = BOT_IDENTITY_COLORS[identityKey(cliType)];
  return {
    color: identity,
  };
}
