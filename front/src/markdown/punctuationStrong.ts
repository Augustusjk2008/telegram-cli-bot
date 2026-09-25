import type { Root } from "mdast";

type MarkdownNode = {
  type: string;
  value?: string;
  children?: MarkdownNode[];
  position?: { start: { offset?: number }; end: { offset?: number } };
};

// CommonMark leaves `**句号。**后文` as text because the closing stars sit between punctuation and a letter.
const PUNCTUATION_STRONG = /\*\*([^*\s][^*\r\n]*?(?!\*)[\p{P}\p{S}])\*\*(?=[\p{L}\p{N}])/gu;

function repairText(node: MarkdownNode, source: string) {
  if (!node.children) {
    return;
  }

  for (let index = 0; index < node.children.length; index += 1) {
    const child = node.children[index];
    if (child.type !== "text" || !child.value) {
      repairText(child, source);
      continue;
    }

    const start = child.position?.start.offset;
    const end = child.position?.end.offset;
    if (start === undefined || end === undefined || source.slice(start, end) !== child.value) {
      continue;
    }

    const parts: MarkdownNode[] = [];
    let cursor = 0;
    for (const match of child.value.matchAll(PUNCTUATION_STRONG)) {
      if (match.index > cursor) {
        parts.push({ type: "text", value: child.value.slice(cursor, match.index) });
      }
      parts.push({ type: "strong", children: [{ type: "text", value: match[1] }] });
      cursor = match.index + match[0].length;
    }
    if (parts.length === 0) {
      continue;
    }
    if (cursor < child.value.length) {
      parts.push({ type: "text", value: child.value.slice(cursor) });
    }
    node.children.splice(index, 1, ...parts);
    index += parts.length - 1;
  }
}

export function remarkPunctuationStrong() {
  return (tree: Root, file: { value: unknown }) => {
    repairText(tree as unknown as MarkdownNode, String(file.value));
  };
}
