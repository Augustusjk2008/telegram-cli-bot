type TextRange = {
  start: number;
  end: number;
};

type Fence = {
  marker: string;
  quoteDepth: number;
};

type LinePrefix = {
  contentIndex: number;
  indent: number;
  quoteDepth: number;
};

type PendingDelimiter = {
  close: ")" | "]";
  display: boolean;
  index: number;
};

function runLength(value: string, start: number, marker: string) {
  let end = start;
  while (value[end] === marker) {
    end += 1;
  }
  return end - start;
}

function lineEnd(value: string, start: number) {
  const newlineIndex = value.indexOf("\n", start);
  return newlineIndex < 0 ? value.length : newlineIndex + 1;
}

function lineWithoutEnding(value: string, start: number, end: number) {
  return value.slice(start, end).replace(/\r?\n$/, "");
}

function indentationWidth(value: string, start: number, end: number) {
  let width = 0;
  for (let index = start; index < end; index += 1) {
    width += value[index] === "\t" ? 4 : 1;
  }
  return width;
}

function consumeLinePrefix(line: string, allowLists: boolean): LinePrefix {
  let contentIndex = 0;
  let quoteDepth = 0;

  while (contentIndex < line.length) {
    const whitespaceStart = contentIndex;
    while (line[contentIndex] === " " || line[contentIndex] === "\t") {
      contentIndex += 1;
    }
    const indent = indentationWidth(line, whitespaceStart, contentIndex);

    if (indent <= 3 && line[contentIndex] === ">") {
      quoteDepth += 1;
      contentIndex += 1;
      if (line[contentIndex] === " " || line[contentIndex] === "\t") {
        contentIndex += 1;
      }
      continue;
    }

    if (allowLists && indent <= 3) {
      const listMarker = line.slice(contentIndex).match(/^(?:[-+*]|\d{1,9}[.)])[ \t]+/);
      if (listMarker) {
        contentIndex += listMarker[0].length;
        continue;
      }
    }

    return { contentIndex, indent, quoteDepth };
  }

  return { contentIndex, indent: 0, quoteDepth };
}

function parseFenceOpening(line: string): Fence | null {
  const prefix = consumeLinePrefix(line, true);
  if (prefix.indent > 3) {
    return null;
  }

  const match = line.slice(prefix.contentIndex).match(/^(`{3,}|~{3,})(.*)$/);
  if (!match || (match[1][0] === "`" && match[2].includes("`"))) {
    return null;
  }
  return { marker: match[1], quoteDepth: prefix.quoteDepth };
}

function isFenceClosing(line: string, fence: Fence) {
  const prefix = consumeLinePrefix(line, false);
  if (prefix.quoteDepth !== fence.quoteDepth || prefix.indent > 3) {
    return false;
  }

  const marker = fence.marker[0];
  const closingFence = new RegExp(`^${marker}{${fence.marker.length},}[ \\t]*$`);
  return closingFence.test(line.slice(prefix.contentIndex));
}

function fencedCodeEnd(markdown: string, start: number, fence: Fence) {
  let cursor = lineEnd(markdown, start);
  while (cursor < markdown.length) {
    const end = lineEnd(markdown, cursor);
    if (isFenceClosing(lineWithoutEnding(markdown, cursor, end), fence)) {
      return end;
    }
    cursor = end;
  }
  return markdown.length;
}

function isIndentedCodeLine(line: string) {
  const prefix = consumeLinePrefix(line, true);
  return prefix.indent >= 4 && line.slice(prefix.contentIndex).trim().length > 0;
}

function isEscapedMarker(value: string, index: number) {
  let backslashCount = 0;
  for (let cursor = index - 1; cursor >= 0 && value[cursor] === "\\"; cursor -= 1) {
    backslashCount += 1;
  }
  return backslashCount % 2 === 1;
}

function matchingRunEnd(value: string, start: number, marker: string, markerLength: number) {
  let cursor = start;
  while (cursor < value.length) {
    const markerStart = value.indexOf(marker, cursor);
    if (markerStart < 0) {
      return -1;
    }
    const nextRunLength = runLength(value, markerStart, marker);
    if (nextRunLength === markerLength && !isEscapedMarker(value, markerStart)) {
      return markerStart + nextRunLength;
    }
    cursor = markerStart + nextRunLength;
  }
  return -1;
}

function protectedMarkdownRanges(markdown: string) {
  const ranges: TextRange[] = [];
  let cursor = 0;

  while (cursor < markdown.length) {
    if (cursor === 0 || markdown[cursor - 1] === "\n") {
      const end = lineEnd(markdown, cursor);
      const line = lineWithoutEnding(markdown, cursor, end);
      const fence = parseFenceOpening(line);
      if (fence) {
        const codeEnd = fencedCodeEnd(markdown, cursor, fence);
        ranges.push({ start: cursor, end: codeEnd });
        cursor = codeEnd;
        continue;
      }
      if (isIndentedCodeLine(line)) {
        ranges.push({ start: cursor, end });
        cursor = end;
        continue;
      }
    }

    const marker = markdown[cursor];
    if ((marker === "`" || marker === "$") && !isEscapedMarker(markdown, cursor)) {
      const markerLength = runLength(markdown, cursor, marker);
      const protectedEnd = matchingRunEnd(
        markdown,
        cursor + markerLength,
        marker,
        markerLength,
      );
      if (protectedEnd < 0) {
        cursor += markerLength;
        continue;
      }
      ranges.push({
        start: cursor,
        end: protectedEnd,
      });
      cursor = protectedEnd;
      continue;
    }

    cursor += 1;
  }

  return ranges;
}

function standaloneDisplayDelimiters(markdown: string) {
  const indexes = new Set<number>();
  let cursor = 0;

  while (cursor < markdown.length) {
    const end = lineEnd(markdown, cursor);
    const line = lineWithoutEnding(markdown, cursor, end);
    const prefix = consumeLinePrefix(line, true);
    if (prefix.indent <= 3) {
      const logicalLine = line.slice(prefix.contentIndex).trimEnd();
      if (logicalLine === "\\[" || logicalLine === "\\]") {
        indexes.add(cursor + prefix.contentIndex);
      }
    }
    cursor = end;
  }

  return indexes;
}

function normalizeTextRange(
  value: string,
  baseOffset: number,
  displayDelimiters: ReadonlySet<number>,
) {
  let pending: PendingDelimiter | null = null;
  let result = "";
  let unchangedStart = 0;
  let cursor = 0;

  while (cursor < value.length) {
    if (value[cursor] !== "\\") {
      cursor += 1;
      continue;
    }

    const backslashRunLength = runLength(value, cursor, "\\");
    const delimiterIndex = cursor + backslashRunLength - 1;
    const delimiterCharacter = value[delimiterIndex + 1];
    if (backslashRunLength % 2 === 0 || !"()[]".includes(delimiterCharacter || "")) {
      cursor += backslashRunLength;
      continue;
    }

    const absoluteDelimiterIndex = baseOffset + delimiterIndex;
    if (
      pending
      && delimiterCharacter === pending.close
      && (!pending.display || displayDelimiters.has(absoluteDelimiterIndex))
    ) {
      result += value.slice(unchangedStart, pending.index);
      result += "$$";
      result += value.slice(pending.index + 2, delimiterIndex);
      result += "$$";
      unchangedStart = delimiterIndex + 2;
      pending = null;
      cursor = delimiterIndex + 2;
      continue;
    }

    if (delimiterCharacter === "(" || delimiterCharacter === "[") {
      const display = delimiterCharacter === "[";
      if (!display || displayDelimiters.has(absoluteDelimiterIndex)) {
        pending = {
          close: display ? "]" : ")",
          display,
          index: delimiterIndex,
        };
      }
    }
    cursor = delimiterIndex + 2;
  }

  return result + value.slice(unchangedStart);
}

export function normalizeLatexMathDelimiters(markdown: string) {
  if (!markdown.includes("\\(") && !markdown.includes("\\[")) {
    return markdown;
  }

  const protectedRanges = protectedMarkdownRanges(markdown);
  const displayDelimiters = standaloneDisplayDelimiters(markdown);
  let result = "";
  let cursor = 0;

  for (const range of protectedRanges) {
    result += normalizeTextRange(
      markdown.slice(cursor, range.start),
      cursor,
      displayDelimiters,
    );
    result += markdown.slice(range.start, range.end);
    cursor = range.end;
  }

  return result + normalizeTextRange(markdown.slice(cursor), cursor, displayDelimiters);
}
