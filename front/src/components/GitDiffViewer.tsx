import { clsx } from "clsx";
import { useLayoutEffect, useMemo, useRef, useState } from "react";
import type { GitDiffSource } from "../services/types";

export type GitDiffLineKind = "meta" | "hunk" | "add" | "delete" | "context";
export type GitDiffViewMode = "full" | "diff" | "split";
type VisibleGitDiffLineKind = GitDiffLineKind;

type VisibleGitDiffLine = {
  line: string;
  lineNumber: number | null;
  kind: VisibleGitDiffLineKind;
};

type SideBySideCell = {
  line: string;
  lineNumber: number | null;
  patchIndex: number | null;
  kind: VisibleGitDiffLineKind | "empty";
};

type DiffSide = "left" | "right";

type SideBySideRow =
  | { type: "meta" | "hunk"; line: string }
  | { type: "line"; left: SideBySideCell; right: SideBySideCell };

type GitDiffViewerProps = {
  content: string;
  source?: GitDiffSource;
  onQuote?: (quote: string) => void;
  testId?: string;
  className?: string;
  ariaLabel?: string;
  emptyLabel?: string;
  enableSideBySide?: boolean;
  defaultViewMode?: GitDiffViewMode;
};

export function parseGitDiffLineKind(line: string): GitDiffLineKind {
  if (
    line.startsWith("diff --git")
    || line.startsWith("index ")
    || line.startsWith("--- ")
    || line.startsWith("+++ ")
    || line.startsWith("rename ")
    || line.startsWith("copy ")
    || line.startsWith("old mode ")
    || line.startsWith("new mode ")
    || line.startsWith("similarity index ")
    || line.startsWith("dissimilarity index ")
    || line.startsWith("new file ")
    || line.startsWith("deleted file ")
    || line.startsWith("Binary files ")
    || line === "GIT binary patch"
    || line.startsWith("literal ")
    || line.startsWith("delta ")
    || line.startsWith("\\ No newline at end of file")
  ) {
    return "meta";
  }
  if (line.startsWith("@@")) {
    return "hunk";
  }
  if (line.startsWith("+")) {
    return "add";
  }
  if (line.startsWith("-")) {
    return "delete";
  }
  return "context";
}

type PatchLine = {
  line: string;
  kind: GitDiffLineKind;
  index: number;
  oldNumber: number | null;
  newNumber: number | null;
};

function parsePatchLines(content: string): PatchLine[] {
  let oldNumber: number | null = null;
  let newNumber: number | null = null;
  let oldEnd = 0;
  let newEnd = 0;
  return (content || "").split(/\r?\n/).map((line, index) => {
    // Inside a hunk, removed and added text can itself look like a --- or +++ file header.
    let kind: GitDiffLineKind;
    if (oldNumber !== null && oldNumber < oldEnd && line.startsWith("-")) kind = "delete";
    else if (newNumber !== null && newNumber < newEnd && line.startsWith("+")) kind = "add";
    else kind = parseGitDiffLineKind(line);
    if (kind === "hunk") {
      const header = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/.exec(line);
      oldNumber = header ? Number(header[1]) : null;
      newNumber = header ? Number(header[3]) : null;
      oldEnd = (oldNumber ?? 0) + Number(header?.[2] ?? 1);
      newEnd = (newNumber ?? 0) + Number(header?.[4] ?? 1);
    } else if (line.startsWith("diff --git")) {
      oldNumber = newNumber = null;
    }
    const item = { line, kind, index, oldNumber, newNumber };
    const context = kind === "context" && line.startsWith(" ");
    if ((context || kind === "delete") && oldNumber !== null) oldNumber++;
    if ((context || kind === "add") && newNumber !== null) newNumber++;
    return item;
  });
}

export function visibleGitDiffLines(content: string, viewMode: GitDiffViewMode = "full"): VisibleGitDiffLine[] {
  const lines: VisibleGitDiffLine[] = [];
  for (const { line, kind, oldNumber, newNumber } of parsePatchLines(content)) {
    if (viewMode === "diff" && kind !== "add" && kind !== "delete") continue;
    if (kind === "context" && (!line.startsWith(" ") || newNumber === null)) continue;
    const lineNumber = kind === "delete" ? oldNumber : kind === "add" || kind === "context" ? newNumber : null;
    lines.push({ line, kind, lineNumber });
  }
  return lines;
}

function sideBySideCell(item: PatchLine | undefined, side: DiffSide): SideBySideCell {
  if (!item) return { line: "", lineNumber: null, patchIndex: null, kind: "empty" };
  return {
    line: item.line.slice(1),
    kind: item.kind,
    patchIndex: item.index,
    lineNumber: side === "left" ? item.oldNumber : item.newNumber,
  };
}

export function sideBySideGitDiffRows(content: string): SideBySideRow[] {
  const rows: SideBySideRow[] = [];
  const lines = parsePatchLines(content);
  for (let index = 0; index < lines.length;) {
    const item = lines[index];
    if (item.kind === "delete" || item.kind === "add") {
      const deleted: PatchLine[] = [];
      const added: PatchLine[] = [];
      const metadata: string[] = [];
      while (lines[index]?.kind === "delete") deleted.push(lines[index++]);
      while (lines[index]?.line.startsWith("\\ No newline at end of file")) metadata.push(lines[index++].line);
      while (lines[index]?.kind === "add") added.push(lines[index++]);
      for (let i = 0; i < Math.max(deleted.length, added.length); i++) {
        rows.push({ type: "line", left: sideBySideCell(deleted[i], "left"), right: sideBySideCell(added[i], "right") });
      }
      for (const line of metadata) rows.push({ type: "meta", line });
      continue;
    }
    if (item.kind === "hunk" || item.kind === "meta") {
      rows.push({ type: item.kind, line: item.line });
    } else if (item.line.startsWith(" ")) {
      rows.push({ type: "line", left: sideBySideCell(item, "left"), right: sideBySideCell(item, "right") });
    }
    index++;
  }
  return rows;
}

function gitDiffLineClass(kind: VisibleGitDiffLineKind) {
  if (kind === "add") return "bg-[var(--diff-added-background)] text-[var(--diff-added-text)]";
  if (kind === "delete") return "bg-[var(--diff-deleted-background)] text-[var(--diff-deleted-text)]";
  if (kind === "hunk") return "bg-[var(--diff-hunk-background)] text-[var(--diff-hunk-text)]";
  if (kind === "meta") return "text-[var(--muted)]";
  return "text-[var(--text)]";
}

function sideBySideCellClass(kind: SideBySideCell["kind"]) {
  if (kind === "empty") return "text-[var(--text)]";
  return gitDiffLineClass(kind);
}

function lineRanges(numbers: number[]) {
  const ranges: string[] = [];
  for (let i = 0; i < numbers.length; i++) {
    const first = numbers[i];
    while (numbers[i + 1] === numbers[i] + 1) i++;
    ranges.push(first === numbers[i] ? String(first) : `${first}–${numbers[i]}`);
  }
  return ranges.join("、");
}

function selectedDiffQuote(container: HTMLElement, rows: SideBySideRow[], source: GitDiffSource) {
  const selection = container.ownerDocument.getSelection();
  if (!selection?.rangeCount || selection.isCollapsed) return "";
  const range = selection.getRangeAt(0);
  if (!container.contains(range.commonAncestorContainer)) return "";
  const elementFor = (node: Node) => node instanceof Element ? node : node.parentElement;
  const start = elementFor(range.startContainer);
  const end = elementFor(range.endContainer);
  const sideFor = (element: Element | null) => element?.closest<HTMLElement>("[data-diff-side]")?.dataset.diffSide;
  const startSide = sideFor(start);
  // The DOM range crosses the opposite column on its way to the next row.
  const singleSide = startSide === sideFor(end) ? startSide : undefined;
  const first = range.startContainer === container ? range.startOffset
    : Number(start?.closest<HTMLElement>("[data-diff-row]")?.dataset.diffRow ?? 0);
  const last = range.endContainer === container ? range.endOffset - 1
    : Number(end?.closest<HTMLElement>("[data-diff-row]")?.dataset.diffRow ?? rows.length - 1);
  const lines = new Map<number, string>();
  const numbers: Record<DiffSide, number[]> = { left: [], right: [] };
  for (let index = first; index <= last; index++) {
    const row = rows[index];
    if (row.type !== "line") continue;
    for (const side of ["left", "right"] as const) {
      const cell = row[side];
      if ((singleSide && side !== singleSide) || cell.patchIndex === null || cell.lineNumber === null) continue;
      if (index === first || index === last) {
        const code = container.children[index].querySelector(`[data-diff-side="${side}"] [data-diff-code]`)?.firstChild;
        if (!code || !range.intersectsNode(code)
          || (range.endContainer === code && range.endOffset === 0)
          || (range.startContainer === code && range.startOffset === code.textContent?.length)) continue;
      }
      numbers[side].push(cell.lineNumber);
      const prefix = cell.kind === "add" ? "+" : cell.kind === "delete" ? "-" : " ";
      lines.set(cell.patchIndex, prefix + cell.line);
    }
  }
  if (!lines.size) return "";
  const locations = [
    numbers.left.length && `旧 ${lineRanges(numbers.left)} 行`,
    numbers.right.length && `新 ${lineRanges(numbers.right)} 行`,
  ].filter(Boolean).join(" / ");
  const patch = Array.from(lines.keys()).sort((a, b) => a - b).map((index) => lines.get(index)).join("\n");
  const fenceLength = patch.match(/`+/g)?.reduce((max, run) => Math.max(max, run.length + 1), 3) ?? 3;
  const fence = "`".repeat(fenceLength);
  return `${source.path} · ${source.staged ? "已暂存" : "工作区"} Diff · ${locations}\n${fence}diff\n${patch}\n${fence}`;
}

function SideBySideCellView({ cell, side }: { cell: SideBySideCell; side: DiffSide }) {
  return (
    <div
      data-diff-kind={cell.kind}
      data-diff-side={side}
      className={clsx("grid min-w-0 grid-cols-[3.5rem_minmax(0,1fr)] gap-3 px-3 py-0.5", sideBySideCellClass(cell.kind))}
    >
      <span className="select-none text-right text-[var(--diff-line-number)]">{cell.lineNumber ?? ""}</span>
      <span data-diff-code className="min-w-0 whitespace-pre-wrap break-all">{cell.line || "\u00a0"}</span>
    </div>
  );
}

export function GitDiffViewer({
  content,
  source,
  onQuote,
  testId = "git-diff-content",
  className = "h-full min-h-0 p-3 text-xs leading-6",
  ariaLabel = "Git Diff 内容",
  emptyLabel = "无可显示的内容",
  enableSideBySide = false,
  defaultViewMode = "full",
}: GitDiffViewerProps) {
  const [viewMode, setViewMode] = useState<GitDiffViewMode>(
    enableSideBySide ? defaultViewMode : defaultViewMode === "split" ? "full" : defaultViewMode,
  );
  const lines = useMemo(() => viewMode === "split" ? [] : visibleGitDiffLines(content, viewMode), [content, viewMode]);
  const sideBySideRows = useMemo(() => viewMode === "split" ? sideBySideGitDiffRows(content) : [], [content, viewMode]);
  const splitRef = useRef<HTMLDivElement>(null);
  const [quote, setQuote] = useState("");
  useLayoutEffect(() => {
    setQuote("");
    const container = splitRef.current;
    if (!source || !container) return;
    const owner = container.ownerDocument;
    const update = () => setQuote(selectedDiffQuote(container, sideBySideRows, source));
    owner.addEventListener("selectionchange", update);
    return () => {
      owner.removeEventListener("selectionchange", update);
      const selection = owner.getSelection();
      if (selection?.anchorNode && container.contains(selection.anchorNode)) selection.removeAllRanges();
    };
  }, [sideBySideRows, source]);

  return (
    <div
      data-testid={testId}
      data-diff-view-mode={viewMode}
      className={clsx("overflow-auto bg-[var(--editor-bg)] font-mono", className)}
      role="document"
      aria-label={ariaLabel}
    >
      <div className="sticky left-0 top-0 z-10 flex justify-end gap-2 pb-2">
        {quote && (
          <button type="button" disabled={!onQuote}
            className="rounded border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-2 text-xs text-[var(--accent)] disabled:opacity-50"
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => onQuote?.(quote)}
          >引用到聊天</button>
        )}
        <div
          role="group"
          aria-label="Diff 显示模式"
          className="inline-flex rounded border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] p-0.5"
        >
          {([
            ["full", "全文"],
            ["diff", "仅差异"],
            ...(enableSideBySide ? [["split", "并排"] as const] : []),
          ] as const).map(([mode, label]) => (
            <button
              key={mode}
              type="button"
              aria-pressed={viewMode === mode}
              onClick={() => setViewMode(mode)}
              className={clsx(
                "rounded px-2 py-0.5 text-[10px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--workbench-focus-ring)]",
                viewMode === mode
                  ? "bg-[var(--workbench-active-bg)] text-[var(--accent)]"
                  : "text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)]",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      {viewMode === "split" ? (
        sideBySideRows.length > 0 ? (
          <div ref={splitRef} data-testid={`${testId}-side-by-side`} className="min-w-[760px] overflow-hidden">
            {sideBySideRows.map((row, index) => row.type === "line" ? (
              <div data-diff-row={index} key={`${index}-${row.left.lineNumber}-${row.right.lineNumber}`} className="grid grid-cols-2 divide-x divide-[var(--workbench-hairline)]">
                <SideBySideCellView cell={row.left} side="left" />
                <SideBySideCellView cell={row.right} side="right" />
              </div>
            ) : (
              <div
                key={`${index}-${row.type}-${row.line}`}
                data-diff-kind={row.type}
                data-diff-row={index}
                className={clsx("px-3 py-0.5", gitDiffLineClass(row.type))}
              >
                {row.line}
              </div>
            ))}
          </div>
        ) : (
          <div className="px-3 py-2 text-xs text-[var(--muted)]">{emptyLabel}</div>
        )
      ) : lines.length > 0 ? (
        lines.map((item, index) => (
          <div
            key={`${index}-${item.lineNumber}-${item.line}`}
            data-testid="git-diff-line"
            data-diff-kind={item.kind}
            className={clsx("flex gap-3 rounded px-3 py-0.5", gitDiffLineClass(item.kind))}
          >
            <span className="w-8 shrink-0 select-none text-right text-[var(--diff-line-number)]">{item.lineNumber ?? ""}</span>
            <span className="min-w-0 flex-1 whitespace-pre-wrap break-all">{item.line}</span>
          </div>
        ))
      ) : (
        <div className="px-3 py-2 text-xs text-[var(--muted)]">{emptyLabel}</div>
      )}
    </div>
  );
}
