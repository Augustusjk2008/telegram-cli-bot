import { clsx } from "clsx";

export type GitDiffLineKind = "meta" | "hunk" | "add" | "delete" | "context";
type VisibleGitDiffLineKind = "add" | "delete" | "context";

type VisibleGitDiffLine = {
  line: string;
  lineNumber: number;
  kind: VisibleGitDiffLineKind;
};

type GitDiffViewerProps = {
  content: string;
  testId?: string;
  className?: string;
  ariaLabel?: string;
  emptyLabel?: string;
};

export function parseGitDiffLineKind(line: string): GitDiffLineKind {
  if (
    line.startsWith("diff --git")
    || line.startsWith("index ")
    || line.startsWith("--- ")
    || line.startsWith("+++ ")
    || line.startsWith("rename ")
    || line.startsWith("new file ")
    || line.startsWith("deleted file ")
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

export function visibleGitDiffLines(content: string): VisibleGitDiffLine[] {
  const visibleLines: VisibleGitDiffLine[] = [];
  let oldLineNumber: number | null = null;
  let newLineNumber: number | null = null;

  for (const line of (content || "").split(/\r?\n/)) {
    const kind = parseGitDiffLineKind(line);

    if (kind === "hunk") {
      const match = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);
      oldLineNumber = match ? Number(match[1]) : null;
      newLineNumber = match ? Number(match[2]) : null;
    } else if (kind === "delete" && oldLineNumber !== null) {
      visibleLines.push({ line, lineNumber: oldLineNumber, kind });
      oldLineNumber += 1;
    } else if (kind === "add" && newLineNumber !== null) {
      visibleLines.push({ line, lineNumber: newLineNumber, kind });
      newLineNumber += 1;
    } else if (kind === "context" && line.startsWith(" ")) {
      const lineNumber = newLineNumber ?? oldLineNumber;
      if (lineNumber !== null) {
        visibleLines.push({ line, lineNumber, kind });
      }
      if (oldLineNumber !== null) oldLineNumber += 1;
      if (newLineNumber !== null) newLineNumber += 1;
    }
  }

  return visibleLines;
}

function gitDiffLineClass(kind: VisibleGitDiffLineKind) {
  if (kind === "add") return "bg-emerald-50 text-emerald-700";
  if (kind === "delete") return "bg-red-50 text-red-700";
  return "text-[var(--text)]";
}

export function GitDiffViewer({
  content,
  testId = "git-diff-content",
  className = "h-full min-h-0 p-3 text-xs leading-6",
  ariaLabel = "Git Diff 内容",
  emptyLabel = "无可显示的内容",
}: GitDiffViewerProps) {
  const lines = visibleGitDiffLines(content);

  return (
    <div
      data-testid={testId}
      className={clsx("overflow-auto bg-[var(--editor-bg)] font-mono", className)}
      role="document"
      aria-label={ariaLabel}
    >
      {lines.length > 0 ? (
        lines.map((item, index) => (
          <div
            key={`${index}-${item.lineNumber}-${item.line}`}
            data-testid="git-diff-line"
            data-diff-kind={item.kind}
            className={clsx("flex gap-3 rounded px-3 py-0.5", gitDiffLineClass(item.kind))}
          >
            <span className="w-8 shrink-0 select-none text-right text-slate-400">{item.lineNumber}</span>
            <span className="min-w-0 flex-1 whitespace-pre-wrap break-all">{item.line}</span>
          </div>
        ))
      ) : (
        <div className="px-3 py-2 text-xs text-[var(--muted)]">{emptyLabel}</div>
      )}
    </div>
  );
}
