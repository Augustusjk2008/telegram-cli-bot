export const JSON_PREVIEW_MAX_BYTES = 4 * 1024 * 1024;

export type JsonPreviewResult = {
  content: string;
  status: "formatted" | "incomplete" | "empty" | "invalid" | "too-large";
};

function isJsonWhitespace(character: string) {
  return character === " " || character === "\t" || character === "\r" || character === "\n";
}

export function formatJsonPreview(content: string, isFullContent: boolean): JsonPreviewResult {
  if (!isFullContent) {
    return { content, status: "incomplete" };
  }
  if (content.length === 0) {
    return { content, status: "empty" };
  }
  try {
    // Only validate: serializing the parsed value would lose duplicate keys and number literals.
    JSON.parse(content);
  } catch {
    return { content, status: "invalid" };
  }

  const fallback: JsonPreviewResult = { content, status: "too-large" };
  const chunks: string[] = [];
  let outputBytes = 0;
  let depth = 0;
  let index = 0;

  function append(text: string) {
    if (outputBytes + text.length > JSON_PREVIEW_MAX_BYTES) {
      return false;
    }
    // Count UTF-8 incrementally, including surrogate pairs and lone surrogates.
    for (const character of text) {
      const codePoint = character.codePointAt(0)!;
      outputBytes += codePoint <= 0x7f ? 1 : codePoint <= 0x7ff ? 2 : codePoint <= 0xffff ? 3 : 4;
      if (outputBytes > JSON_PREVIEW_MAX_BYTES) {
        return false;
      }
    }
    chunks.push(text);
    return true;
  }

  function newline() {
    const bytes = 1 + depth * 2;
    // Check before allocating indentation so deeply nested input cannot expand without bound.
    if (outputBytes + bytes > JSON_PREVIEW_MAX_BYTES) {
      return false;
    }
    outputBytes += bytes;
    chunks.push("\n" + "  ".repeat(depth));
    return true;
  }

  while (index < content.length) {
    const character = content[index];
    if (isJsonWhitespace(character)) {
      index += 1;
      continue;
    }
    if (character === "{" || character === "[") {
      index += 1;
      while (isJsonWhitespace(content[index])) index += 1;
      const closing = character === "{" ? "}" : "]";
      if (content[index] === closing) {
        if (!append(character + closing)) return fallback;
        index += 1;
      } else {
        depth += 1;
        if (!append(character) || !newline()) return fallback;
      }
    } else if (character === "}" || character === "]") {
      depth -= 1;
      if (!newline() || !append(character)) return fallback;
      index += 1;
    } else if (character === ",") {
      if (!append(",") || !newline()) return fallback;
      index += 1;
    } else if (character === ":") {
      if (!append(": ")) return fallback;
      index += 1;
    } else {
      const start = index;
      if (character === '"') {
        index += 1;
        while (index < content.length) {
          const next = content[index++];
          if (next === "\\") index += 1;
          else if (next === '"') break;
        }
      } else {
        while (index < content.length && !isJsonWhitespace(content[index]) && !",]}".includes(content[index])) {
          index += 1;
        }
      }
      if (!append(content.slice(start, index))) return fallback;
    }
  }

  return { content: chunks.join(""), status: "formatted" };
}
