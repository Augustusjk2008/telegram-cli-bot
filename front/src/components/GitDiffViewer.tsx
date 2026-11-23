import { clsx } from "clsx";
import { useState } from "react";

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
  kind: VisibleGitDiffLineKind | "empty";
};

type SideBySideRow =
  | { type: "meta" | "hunk"; line: string }
  | { type: "line"; left: SideBySideCell; right: SideBySideCell };

type GitDiffViewerProps = {
  content: string;
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
  if (line.startsWith("+") && !line.startsWith("+++")) {
    return "add";
  }
  if (line.startsWith("-") && !line.startsWith("---")) {
    return "delete";
  }
  return "context";
}

export function visibleGitDiffLines(content: string, viewMode: GitDiffViewMode = "full"): VisibleGitDiffLine[] {
  const visibleLines: VisibleGitDiffLine[] = [];
  let oldLineNumber: number | null = null;
  let newLineNumber: number | null = null;

  for (const line of (content || "").split(/\r?\n/)) {
    const kind = parseGitDiffLineKind(line);

    if (kind === "meta") {
      if (line) {
        visibleLines.push({ line, lineNumber: null, kind });
      }
    } else if (kind === "hunk") {
      visibleLines.push({ line, lineNumber: null, kind });
      const match = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);
      oldLineNumber = match ? Number(match[1]) : null;
      newLineNumber = match ? Number(match[2]) : null;
    } else if (kind === "delete" && oldLineNumber !== null) {
      visibleLines.push({ line, lineNumber: oldLineNumber, kind });
      oldLineNumber += 1;
    } else if (kind === "add" && newLineNumber !== null) {
      visibleLines.push({ line, lineNumber: newLineNumber, kind });
      newLineNumber += 1;
    } else if (kind === "delete" || kind === "add") {
      visibleLines.push({ line, lineNumber: null, kind });
    } else if (kind === "context" && line.startsWith(" ")) {
      const lineNumber = newLineNumber ?? oldLineNumber;
      if (lineNumber !== null) {
        visibleLines.push({ line, lineNumber, kind });
      }
      if (oldLineNumber !== null) oldLineNumber += 1;
      if (newLineNumber !== null) newLineNumber += 1;
    }
  }

  return viewMode === "diff"
    ? visibleLines.filter((item) => item.kind === "add" || item.kind === "delete")
    : visibleLines;
}

function sideBySideCell(line: string, kind: GitDiffLineKind, lineNumber: number | null): SideBySideCell {
  return {
    line: kind === "add" || kind === "delete" || kind === "context" ? line.slice(1) : line,
    lineNumber,
    kind,
  };
}

function emptySideBySideCell(): SideBySideCell {
  return { line: "", lineNumber: null, kind: "empty" };
}

export function sideBySideGitDiffRows(content: string): SideBySideRow[] {
  const rows: SideBySideRow[] = [];
  const lines = (content || "").split(/\r?\n/);
  let oldLineNumber: number | null = null;
  let newLineNumber: number | null = null;

  for (let index = 0; index < lines.length;) {
    const line = lines[index];
    const kind = parseGitDiffLineKind(line);

    if (kind === "meta") {
      if (line) rows.push({ type: "meta", line });
      index += 1;
      continue;
    }

    if (kind === "hunk") {
      rows.push({ type: "hunk", line });
      const match = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);
      oldLineNumber = match ? Number(match[1]) : null;
      newLineNumber = match ? Number(match[2]) : null;
      index += 1;
      continue;
    }

    if (kind === "context" && line.startsWith(" ")) {
      rows.push({
        type: "line",
        left: sideBySideCell(line, kind, oldLineNumber),
        right: sideBySideCell(line, kind, newLineNumber),
      });
      if (oldLineNumber !== null) oldLineNumber += 1;
      if (newLineNumber !== null) newLineNumber += 1;
      index += 1;
      continue;
    }

    if (kind === "delete" || kind === "add") {
      const deleted: SideBySideCell[] = [];
      const added: SideBySideCell[] = [];
      const changeMetadata: string[] = [];
      while (index < lines.length && parseGitDiffLineKind(lines[index]) === "delete") {
        deleted.push(sideBySideCell(lines[index], "delete", oldLineNumber));
        if (oldLineNumber !== null) oldLineNumber += 1;
        index += 1;
      }
      while (index < lines.length
        && parseGitDiffLineKind(lines[index]) === "meta"
        && lines[index].startsWith("\\ No newline at end of file")) {
        changeMetadata.push(lines[index]);
        index += 1;
      }
      while (index < lines.length && parseGitDiffLineKind(lines[index]) === "add") {
        added.push(sideBySideCell(lines[index], "add", newLineNumber));
        if (newLineNumber !== null) newLineNumber += 1;
        index += 1;
      }
      const rowCount = Math.max(deleted.length, added.length);
      for (let rowIndex = 0; rowIndex < rowCount; rowIndex += 1) {
        rows.push({
          type: "line",
          left: deleted[rowIndex] || emptySideBySideCell(),
          right: added[rowIndex] || emptySideBySideCell(),
        });
      }
      for (const metadata of changeMetadata) rows.push({ type: "meta", line: metadata });
      continue;
    }

    index += 1;
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

function SideBySideCellView({ cell }: { cell: SideBySideCell }) {
  return (
    <div
      data-diff-kind={cell.kind}
      className={clsx("grid min-w-0 grid-cols-[3.5rem_minmax(0,1fr)] gap-3 px-3 py-0.5", sideBySideCellClass(cell.kind))}
    >
      <span className="select-none text-right text-[var(--diff-line-number)]">{cell.lineNumber ?? ""}</span>
      <span className="min-w-0 whitespace-pre-wrap break-all">{cell.line || "\u00a0"}</span>
    </div>
  );
}

export function GitDiffViewer({
  content,
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
  const lines = visibleGitDiffLines(content, viewMode);
  const sideBySideRows = viewMode === "split" ? sideBySideGitDiffRows(content) : [];

  return (
    <div
      data-testid={testId}
      data-diff-view-mode={viewMode}
      className={clsx("overflow-auto bg-[var(--editor-bg)] font-mono", className)}
      role="document"
      aria-label={ariaLabel}
    >
      <div className="sticky top-0 z-10 flex justify-end pb-2">
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
          <div data-testid={`${testId}-side-by-side`} className="min-w-[760px] overflow-hidden">
            {sideBySideRows.map((row, index) => row.type === "line" ? (
              <div key={`${index}-${row.left.lineNumber}-${row.right.lineNumber}`} className="grid grid-cols-2 divide-x divide-[var(--workbench-hairline)]">
                <SideBySideCellView cell={row.left} />
                <SideBySideCellView cell={row.right} />
              </div>
            ) : (
              <div
                key={`${index}-${row.type}-${row.line}`}
                data-diff-kind={row.type}
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
