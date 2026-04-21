import { AlertCircle, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { WorkspaceProblem } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  botAlias: string;
  client: WebBotClient;
  refreshKey: number;
  onOpenFile: (path: string, line?: number) => void | Promise<void>;
};

const SEVERITY_CLASS: Record<WorkspaceProblem["severity"], string> = {
  error: "text-red-600",
  warning: "text-amber-600",
  info: "text-sky-600",
};

export function ProblemsPane({ botAlias, client, refreshKey, onOpenFile }: Props) {
  const [items, setItems] = useState<WorkspaceProblem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadProblems() {
    setLoading(true);
    try {
      const nextItems = await client.getProblems(botAlias);
      setItems(nextItems);
      setError("");
    } catch (caught) {
      setItems([]);
      setError(caught instanceof Error ? caught.message : "读取问题失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadProblems();
  }, [botAlias, client, refreshKey]);

  const grouped = useMemo(() => {
    const groups = new Map<string, WorkspaceProblem[]>();
    items.forEach((item) => {
      groups.set(item.path, [...(groups.get(item.path) || []), item]);
    });
    return Array.from(groups.entries());
  }, [items]);

  return (
    <section className="flex h-full min-h-0 flex-col bg-[var(--surface)]">
      <div className="flex items-center justify-between gap-2 border-b border-[var(--border)] px-3 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <AlertCircle className="h-4 w-4 text-[var(--muted)]" />
          <h2 className="text-sm font-semibold text-[var(--text)]">问题</h2>
        </div>
        <button
          type="button"
          aria-label="刷新问题"
          onClick={() => void loadProblems()}
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--border)] text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)]"
        >
          <RefreshCw className="h-4 w-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto py-1">
        {loading ? <div className="px-3 py-3 text-sm text-[var(--muted)]">加载中...</div> : null}
        {error ? <div className="px-3 py-3 text-sm text-red-600">{error}</div> : null}
        {!loading && !error && items.length === 0 ? <div className="px-3 py-3 text-sm text-[var(--muted)]">无问题</div> : null}
        {grouped.map(([path, problems]) => (
          <div key={path} className="border-b border-[var(--border)] py-2">
            <div className="px-3 pb-1 font-mono text-xs font-semibold text-[var(--muted)]">{path}</div>
            {problems.map((problem) => (
              <button
                key={`${problem.path}:${problem.line}:${problem.column}:${problem.message}`}
                type="button"
                aria-label={`打开 ${problem.path} 第 ${problem.line} 行`}
                onClick={() => void onOpenFile(problem.path, problem.line)}
                className="flex w-full min-w-0 flex-col gap-1 px-3 py-2 text-left hover:bg-[var(--surface-strong)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent)]"
              >
                <span className="flex min-w-0 items-center gap-2 text-xs">
                  <span className={SEVERITY_CLASS[problem.severity]}>{problem.severity}</span>
                  <span className="truncate font-mono text-[var(--muted)]">
                    {problem.line}:{problem.column} · {problem.source}
                  </span>
                </span>
                <span className="line-clamp-2 text-sm text-[var(--text)]">{problem.message}</span>
              </button>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}
