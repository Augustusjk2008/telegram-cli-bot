import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import remarkParse from "remark-parse";
import { unified } from "unified";

type SourcePoint = {
  offset?: number;
};

type SourcePosition = {
  start?: SourcePoint;
  end?: SourcePoint;
};

type MarkdownNode = {
  type: string;
  value?: unknown;
  position?: SourcePosition;
  children?: MarkdownNode[];
};

type SourceRange = {
  start: number;
  end: number;
};

type Replacement = SourceRange & {
  value: string;
};

type HtmlBoundaryTag = SourceRange & {
  name: string;
  closing: boolean;
  selfClosing: boolean;
};

type SourceLine = SourceRange & {
  ending: string;
};

const markdownParser = unified()
  .use(remarkParse)
  .use(remarkGfm)
  .use(remarkMath);

const EDITABLE_NODE_TYPES = new Set(["paragraph", "heading", "tableCell"]);
const PROTECTED_NODE_TYPES = new Set([
  "code",
  "definition",
  "html",
  "image",
  "imageReference",
  "inlineCode",
  "inlineMath",
  "math",
]);
const LINK_NODE_TYPES = new Set(["link", "linkReference"]);
const VOID_HTML_ELEMENTS = new Set([
  "area",
  "base",
  "br",
  "col",
  "embed",
  "hr",
  "img",
  "input",
  "link",
  "meta",
  "param",
  "source",
  "track",
  "wbr",
]);

function sourceRange(node: MarkdownNode): SourceRange | null {
  const start = node.position?.start?.offset;
  const end = node.position?.end?.offset;
  if (!Number.isInteger(start) || !Number.isInteger(end) || start === undefined || end === undefined || end < start) {
    return null;
  }
  return { start, end };
}

function htmlBoundaryTags(node: MarkdownNode, source: string): HtmlBoundaryTag[] {
  const range = sourceRange(node);
  if (!range || node.type !== "html") {
    return [];
  }

  const value = source.slice(range.start, range.end);
  const tags: HtmlBoundaryTag[] = [];
  let cursor = 0;
  while (cursor < value.length) {
    const tagStart = value.indexOf("<", cursor);
    if (tagStart < 0) {
      break;
    }
    if (value.startsWith("<![CDATA[", tagStart)) {
      const cdataEnd = value.indexOf("]]>", tagStart + 9);
      cursor = cdataEnd < 0 ? value.length : cdataEnd + 3;
      continue;
    }
    if (value.startsWith("<!--", tagStart)) {
      const commentEnd = value.indexOf("-->", tagStart + 4);
      cursor = commentEnd < 0 ? value.length : commentEnd + 3;
      continue;
    }
    if (value.startsWith("<?", tagStart)) {
      const instructionEnd = value.indexOf("?>", tagStart + 2);
      cursor = instructionEnd < 0 ? value.length : instructionEnd + 2;
      continue;
    }

    let quote = "";
    let tagEnd = -1;
    for (let index = tagStart + 1; index < value.length; index += 1) {
      const character = value[index];
      if (quote) {
        if (character === quote) {
          quote = "";
        }
        continue;
      }
      if (character === "\"" || character === "'") {
        quote = character;
        continue;
      }
      if (character === ">") {
        tagEnd = index;
        break;
      }
    }
    if (tagEnd < 0) {
      break;
    }

    const tag = value.slice(tagStart, tagEnd + 1);
    const match = /^<\s*(\/?)\s*([A-Za-z][A-Za-z0-9:.-]*)(?=\s|\/?>)/.exec(tag);
    if (match) {
      const name = match[2].toLowerCase();
      const closing = Boolean(match[1]);
      tags.push({
        start: range.start + tagStart,
        end: range.start + tagEnd + 1,
        name,
        closing,
        selfClosing: !closing && (VOID_HTML_ELEMENTS.has(name) || /\/\s*>$/.test(tag)),
      });
    }
    cursor = tagEnd + 1;
  }
  return tags;
}

function protectHtmlElementBodies(tags: HtmlBoundaryTag[], ranges: SourceRange[], sourceLength: number) {
  const stack: HtmlBoundaryTag[] = [];
  const sortedTags = [...tags].sort((left, right) => left.start - right.start || left.end - right.end);
  for (const tag of sortedTags) {
    if (tag.selfClosing) {
      continue;
    }
    if (!tag.closing) {
      stack.push(tag);
      continue;
    }

    let openerIndex = -1;
    for (let index = stack.length - 1; index >= 0; index -= 1) {
      if (stack[index].name === tag.name) {
        openerIndex = index;
        break;
      }
    }
    if (openerIndex < 0) {
      continue;
    }
    const opener = stack[openerIndex];
    ranges.push({ start: opener.start, end: tag.end });
    stack.splice(openerIndex);
  }

  for (const opener of stack) {
    ranges.push({ start: opener.start, end: sourceLength });
  }
}

function collectAstRanges(
  node: MarkdownNode,
  source: string,
  editableRanges: SourceRange[],
  protectedRanges: SourceRange[],
  htmlTags: HtmlBoundaryTag[],
) {
  const range = sourceRange(node);
  if (range && EDITABLE_NODE_TYPES.has(node.type)) {
    editableRanges.push(range);
  }
  if (range && node.type === "html") {
    protectedRanges.push(range);
    htmlTags.push(...htmlBoundaryTags(node, source));
    return;
  }
  if (range && LINK_NODE_TYPES.has(node.type)) {
    const childRanges = (node.children || [])
      .map((child) => sourceRange(child))
      .filter((childRange): childRange is SourceRange => childRange !== null);
    if (source[range.start] !== "[" || !childRanges.length) {
      protectedRanges.push(range);
      return;
    }

    const labelStart = Math.min(...childRanges.map((childRange) => childRange.start));
    const labelEnd = Math.max(...childRanges.map((childRange) => childRange.end));
    protectedRanges.push(
      { start: range.start, end: labelStart },
      { start: labelEnd, end: range.end },
    );
  }
  if (range && PROTECTED_NODE_TYPES.has(node.type)) {
    protectedRanges.push(range);
    return;
  }

  for (const child of node.children || []) {
    collectAstRanges(child, source, editableRanges, protectedRanges, htmlTags);
  }
}

function mergeRanges(ranges: SourceRange[], sourceLength: number): SourceRange[] {
  const sorted = ranges
    .map((range) => ({
      start: Math.max(0, Math.min(sourceLength, range.start)),
      end: Math.max(0, Math.min(sourceLength, range.end)),
    }))
    .filter((range) => range.end > range.start)
    .sort((left, right) => left.start - right.start || left.end - right.end);

  const merged: SourceRange[] = [];
  for (const range of sorted) {
    const previous = merged[merged.length - 1];
    if (previous && range.start <= previous.end) {
      previous.end = Math.max(previous.end, range.end);
    } else {
      merged.push({ ...range });
    }
  }
  return merged;
}

function subtractRanges(range: SourceRange, exclusions: SourceRange[]): SourceRange[] {
  const result: SourceRange[] = [];
  let cursor = range.start;

  let low = 0;
  let high = exclusions.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (exclusions[middle].end <= range.start) {
      low = middle + 1;
    } else {
      high = middle;
    }
  }

  for (let index = low; index < exclusions.length; index += 1) {
    const exclusion = exclusions[index];
    if (exclusion.end <= cursor) {
      continue;
    }
    if (exclusion.start >= range.end) {
      break;
    }
    if (exclusion.start > cursor) {
      result.push({ start: cursor, end: Math.min(exclusion.start, range.end) });
    }
    cursor = Math.max(cursor, exclusion.end);
    if (cursor >= range.end) {
      break;
    }
  }

  if (cursor < range.end) {
    result.push({ start: cursor, end: range.end });
  }
  return result;
}

function delimiterIsEscaped(source: string, index: number) {
  let precedingBackslashes = 0;
  for (let cursor = index - 1; cursor >= 0 && source[cursor] === "\\"; cursor -= 1) {
    precedingBackslashes += 1;
  }
  return precedingBackslashes % 2 === 1;
}

function collectSourceLines(source: string): SourceLine[] {
  const lines: SourceLine[] = [];
  let start = 0;
  while (start < source.length) {
    let end = start;
    while (end < source.length && source[end] !== "\n" && source[end] !== "\r") {
      end += 1;
    }
    let ending = "";
    if (source[end] === "\r" && source[end + 1] === "\n") {
      ending = "\r\n";
    } else if (source[end] === "\r" || source[end] === "\n") {
      ending = source[end];
    }
    lines.push({ start, end, ending });
    start = end + ending.length;
  }
  if (!lines.length) {
    lines.push({ start: 0, end: 0, ending: "" });
  }
  return lines;
}

function sourceLineIndex(lines: SourceLine[], offset: number) {
  let low = 0;
  let high = lines.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (lines[middle].start <= offset) {
      low = middle + 1;
    } else {
      high = middle;
    }
  }
  return Math.max(0, low - 1);
}

function preferredLineEnding(lines: SourceLine[], lineIndex: number) {
  if (lines[lineIndex]?.ending) {
    return lines[lineIndex].ending;
  }
  for (let index = lineIndex - 1; index >= 0; index -= 1) {
    if (lines[index].ending) {
      return lines[index].ending;
    }
  }
  for (let index = lineIndex + 1; index < lines.length; index += 1) {
    if (lines[index].ending) {
      return lines[index].ending;
    }
  }
  return "\n";
}

function onlyHorizontalWhitespace(source: string, start: number, end: number) {
  for (let index = start; index < end; index += 1) {
    if (source[index] !== " " && source[index] !== "\t") {
      return false;
    }
  }
  return true;
}

function collectPairedDelimiters(
  source: string,
  range: SourceRange,
  openingDelimiter: string,
  closingDelimiter: string,
  acceptOpening: (index: number) => boolean,
  acceptClosing: (index: number) => boolean,
  onPair: (openingIndex: number, closingIndex: number) => void,
) {
  let pendingOpening = -1;
  let cursor = range.start;

  while (cursor < range.end) {
    if (
      cursor + openingDelimiter.length <= range.end
      && source.startsWith(openingDelimiter, cursor)
    ) {
      if (!delimiterIsEscaped(source, cursor) && acceptOpening(cursor)) {
        pendingOpening = cursor;
      }
      cursor += openingDelimiter.length;
      continue;
    }
    if (
      cursor + closingDelimiter.length <= range.end
      && source.startsWith(closingDelimiter, cursor)
    ) {
      if (!delimiterIsEscaped(source, cursor) && acceptClosing(cursor) && pendingOpening >= 0) {
        onPair(pendingOpening, cursor);
        pendingOpening = -1;
      }
      cursor += closingDelimiter.length;
      continue;
    }
    cursor += 1;
  }
}

function applyReplacements(source: string, replacements: Replacement[]) {
  if (!replacements.length) {
    return source;
  }

  const sorted = [...replacements].sort((left, right) => left.start - right.start || left.end - right.end);
  const result: string[] = [];
  let cursor = 0;
  for (const replacement of sorted) {
    if (replacement.start < cursor) {
      continue;
    }
    result.push(source.slice(cursor, replacement.start), replacement.value);
    cursor = replacement.end;
  }
  result.push(source.slice(cursor));
  return result.join("");
}

export function normalizeLatexMath(content: string) {
  if (!content.includes("\\(") && !content.includes("\\[")) {
    return content;
  }

  let tree: MarkdownNode;
  try {
    tree = markdownParser.parse(content) as MarkdownNode;
  } catch {
    return content;
  }

  const editableRanges: SourceRange[] = [];
  const protectedRanges: SourceRange[] = [];
  const htmlTags: HtmlBoundaryTag[] = [];
  collectAstRanges(tree, content, editableRanges, protectedRanges, htmlTags);
  protectHtmlElementBodies(htmlTags, protectedRanges, content.length);

  const baseExclusions = mergeRanges(protectedRanges, content.length);
  const replacements: Replacement[] = [];
  const displayRanges: SourceRange[] = [];
  const sourceLines = collectSourceLines(content);

  for (const editableRange of editableRanges) {
    for (const range of subtractRanges(editableRange, baseExclusions)) {
      collectPairedDelimiters(
        content,
        range,
        "\\[",
        "\\]",
        (index) => {
          const line = sourceLines[sourceLineIndex(sourceLines, index)];
          return onlyHorizontalWhitespace(content, line.start, index);
        },
        (index) => {
          const line = sourceLines[sourceLineIndex(sourceLines, index)];
          return onlyHorizontalWhitespace(content, index + 2, line.end);
        },
        (openingIndex, closingIndex) => {
          const openingLineIndex = sourceLineIndex(sourceLines, openingIndex);
          const closingLineIndex = sourceLineIndex(sourceLines, closingIndex);
          const openingLine = sourceLines[openingLineIndex];
          const closingLine = sourceLines[closingLineIndex];
          const openingNeedsLineBreak = !onlyHorizontalWhitespace(
            content,
            openingIndex + 2,
            openingLine.end,
          );
          const closingNeedsLineBreak = !onlyHorizontalWhitespace(
            content,
            closingLine.start,
            closingIndex,
          );
          const indentation = content.slice(openingLine.start, openingIndex);
          const openingLineEnding = preferredLineEnding(sourceLines, openingLineIndex);
          const closingLineEnding = preferredLineEnding(sourceLines, closingLineIndex);
          replacements.push(
            {
              start: openingIndex,
              end: openingIndex + 2,
              value: openingNeedsLineBreak ? `$$${openingLineEnding}${indentation}` : "$$",
            },
            {
              start: closingIndex,
              end: closingIndex + 2,
              value: closingNeedsLineBreak ? `${closingLineEnding}${indentation}$$` : "$$",
            },
          );
          displayRanges.push({ start: openingIndex, end: closingIndex + 2 });
        },
      );
    }
  }

  const inlineExclusions = mergeRanges([...baseExclusions, ...displayRanges], content.length);
  for (const editableRange of editableRanges) {
    for (const range of subtractRanges(editableRange, inlineExclusions)) {
      collectPairedDelimiters(
        content,
        range,
        "\\(",
        "\\)",
        () => true,
        () => true,
        (openingIndex, closingIndex) => {
          if (content.slice(openingIndex + 2, closingIndex).includes("$")) {
            return;
          }
          replacements.push(
            { start: openingIndex, end: openingIndex + 2, value: "$" },
            { start: closingIndex, end: closingIndex + 2, value: "$" },
          );
        },
      );
    }
  }

  return applyReplacements(content, replacements);
}
