import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import type { Root, RootContent } from "mdast";

const parser = unified().use(remarkParse).use(remarkGfm).use(remarkMath);

function spokenText(node: Root | RootContent): string {
  switch (node.type) {
    case "text":
    case "inlineCode":
      return node.value;
    case "code":
    case "html":
    case "definition":
    case "image":
    case "imageReference":
    case "math":
    case "inlineMath":
      return "";
    case "break":
      return "\n";
    default: {
      if (!("children" in node)) return "";
      const separator = ["root", "blockquote", "list", "listItem", "table", "tableRow"].includes(node.type) ? "\n" : "";
      return node.children.map((child) => spokenText(child)).join(separator);
    }
  }
}

/** Read Markdown prose without link destinations, code blocks or formatting syntax. */
export function readAloudText(markdown: string): string {
  const visible = markdown.replace(/<(think|thinking)\b[^>]*>[\s\S]*?(?:<\/\1\s*>|$)/gi, "");
  return spokenText(parser.parse(visible) as Root)
    .replace(/[\t ]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/** Short utterances avoid browser limits on long answers; preserve sentence/word boundaries. */
export function splitReadAloudText(text: string, limit = 200): string[] {
  const chunks: string[] = [];
  let remaining = text.trim();
  while (remaining) {
    if (remaining.length <= limit) {
      chunks.push(remaining);
      break;
    }
    const prefix = remaining.slice(0, limit);
    const boundaries = [...prefix.matchAll(/[。！？.!?；;\n]\s*|\s+/g)];
    const last = boundaries.at(-1);
    let end = last && last.index! > limit / 3 ? last.index! + last[0].length : limit;
    // Never split a UTF-16 surrogate pair.
    if (/[\uD800-\uDBFF]/.test(remaining[end - 1])) end -= 1;
    const chunk = remaining.slice(0, end).trim();
    if (chunk) chunks.push(chunk);
    remaining = remaining.slice(end).trimStart();
  }
  return chunks;
}
