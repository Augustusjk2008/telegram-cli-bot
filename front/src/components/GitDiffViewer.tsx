import { clsx } from "clsx";

export type GitDiffLineKind = "meta" | "hunk" | "add" | "delete" | "context";
type VisibleGitDiffLineKind = "add" | "delete";

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
  return (content || "")
    .split(/\r?\n/)
    .map((line, index) => ({ line, lineNumber: index + 1, kind: parseGitDiffLineKind(line) }))
    .filter((item): item is VisibleGitDiffLine => item.kind === "add" || item.kind === "delete");
}

function gitDiffLineClass(kind: VisibleGitDiffLineKind) {
  return kind === "add"
    ? "bg-emerald-50 text-emerald-700"
    : "bg-red-50 text-red-700";
}

export function GitDiffViewer({
  content,
  testId = "git-diff-content",
  className = "h-full min-h-0 p-3 text-xs leading-6",
  ariaLabel = "Git Diff 内容",
  emptyLabel = "无新增或删除内容",
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
        lines.map((item) => (
          <div
            key={`${item.lineNumber}-${item.line}`}
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
