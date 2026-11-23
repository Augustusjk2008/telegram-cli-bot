import type { CodeLocation, WorkspaceSearchMatch } from "../services/types";

export const TEXT_FALLBACK_PROVIDER = "文本搜索";
export const TEXT_FALLBACK_SEARCH_LIMIT = 200;
const TEXT_FALLBACK_RESULT_LIMIT = 60;

const DECLARATION_KEYWORDS = "class|struct|enum|union|namespace|interface|type|typedef|using|def|function|const|let|var|#\\s*define";

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** A symbol worth searching for as plain text: an identifier, not punctuation or a keyword fragment. */
export function isTextFallbackSymbol(symbol: string) {
  return /^[A-Za-z_$][\w$]{1,}$/.test(symbol);
}

/**
 * Turns plain-text matches into jump candidates when no language server could
 * answer. Only whole-word hits count, and lines that look like declarations
 * come first; the result is a guess, never a semantic answer.
 */
export function rankTextFallbackLocations(symbol: string, matches: readonly WorkspaceSearchMatch[]): CodeLocation[] {
  if (!isTextFallbackSymbol(symbol)) return [];
  const name = escapeRegExp(symbol);
  const wholeWord = new RegExp(`(^|[^\\w$])${name}(?![\\w$])`);
  const declaration = new RegExp(`(^|[^\\w$])(${DECLARATION_KEYWORDS})\\b[^=;(]*[^\\w$]${name}(?![\\w$])`);
  // A call-shaped line that does not end a statement is usually a function signature.
  const signature = new RegExp(`(^|[^\\w$.>])${name}\\s*\\([^;]*$`);
  const seen = new Set<string>();
  const ranked: Array<{ score: number; order: number; location: CodeLocation }> = [];
  matches.forEach((match, order) => {
    if (!wholeWord.test(match.preview)) return;
    const line = Math.max(1, Math.trunc(match.line) || 1);
    const key = `${match.path}:${line}`;
    if (seen.has(key)) return;
    seen.add(key);
    // The search reports where its first hit starts, which is close enough to land on the line.
    const column = Math.max(1, Math.trunc(match.column) || 1);
    const start = { line, column };
    const end = { line, column: column + symbol.length };
    ranked.push({
      score: declaration.test(match.preview) ? 2 : signature.test(match.preview) ? 1 : 0,
      order,
      location: {
        targetType: "workspace",
        path: match.path,
        provider: TEXT_FALLBACK_PROVIDER,
        range: { start, end },
        selectionRange: { start, end },
        preview: match.preview.trim().slice(0, 200),
      },
    });
  });
  return ranked
    .sort((left, right) => right.score - left.score || left.order - right.order)
    .slice(0, TEXT_FALLBACK_RESULT_LIMIT)
    .map((entry) => entry.location);
}
