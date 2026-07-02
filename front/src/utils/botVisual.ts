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
