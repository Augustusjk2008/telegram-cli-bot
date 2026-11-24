import type { IBufferLine, ILink, ILinkProvider, Terminal } from "@xterm/xterm";
import { workspaceRelativePath } from "../services/workspacePath";

export type TerminalSourceLocation = { path: string; line: number; column: number };
export type TerminalSourceNavigation = {
  scope: string;
  root: string;
  windows: boolean;
  open: (location: TerminalSourceLocation, isCurrent: () => boolean) => void;
};

// A quote may surround the filename alone or the complete diagnostic location.
const SOURCE_LOCATION = /(?<![^\s([<{=,：])(?:"([^"]+?)"?|'([^']+?)'?|((?:\/?[a-z]:)?[^\s:'"()<>{}]+)):(\d+)(?::(\d+))?(?=$|[\s:,;.)'"\]}>])/gi;

function bufferColumn(line: IBufferLine, offset: number, end: boolean) {
  for (let x = 0; x < line.length;) {
    const cell = line.getCell(x)!;
    const width = cell.getWidth() || 1;
    offset -= cell.getChars().length || 1;
    if (offset < 0) return x + (end ? width : 1);
    x += width;
  }
  return line.length;
}

export function terminalSourceLinkProvider(
  term: Terminal, cwd: string, workspace: Pick<TerminalSourceNavigation, "root" | "windows">,
  open: (location: TerminalSourceLocation) => void,
): ILinkProvider {
  return {
    provideLinks(y, callback) {
      const buffer = term.buffer.active;
      let first = y - 1;
      while (first > 0 && buffer.getLine(first)?.isWrapped) first--;
      const rows: { line: IBufferLine; y: number; start: number; end: number }[] = [];
      let text = "";
      for (let i = first; i < buffer.length; i++) {
        const line = buffer.getLine(i);
        if (!line || (i > first && !line.isWrapped)) break;
        const start = text.length;
        text += line.translateToString(true);
        rows.push({ line, y: i + 1, start, end: text.length });
      }
      const row = rows[y - 1 - first];
      const links: ILink[] = [];
      for (const match of text.matchAll(SOURCE_LOCATION)) {
        const start = match.index;
        const end = start + match[0].length - 1;
        if (!row || end < row.start || start >= row.end) continue;
        const filename = match[1] ?? match[2] ?? match[3];
        const line = Number(match[4]);
        const column = Number(match[5] ?? 1);
        if (/^\d+$/.test(filename) || !Number.isSafeInteger(line) || line < 1 || !Number.isSafeInteger(column) || column < 1) continue;
        const path = workspaceRelativePath(filename, cwd, workspace.root, workspace.windows);
        if (!path) continue;
        const from = rows.find((item) => item.end > start)!;
        const to = rows.find((item) => item.end > end)!;
        links.push({
          text: match[0],
          range: {
            start: { x: bufferColumn(from.line, start - from.start, false), y: from.y },
            end: { x: bufferColumn(to.line, end - to.start, true), y: to.y },
          },
          activate(event) {
            if (event.ctrlKey && event.button === 0 && !term.hasSelection()) open({ path, line, column });
          },
        });
      }
      callback(links);
    },
  };
}
