import { Search } from "lucide-react";
import { useEffect, useState } from "react";
import type { WorkspaceSearchMatch } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  botAlias: string;
  client: WebBotClient;
  onOpenFile: (path: string, line?: number) => void | Promise<void>;
};

export function SearchPane({ botAlias, client, onOpenFile }: Props) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<WorkspaceSearchMatch[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const nextQuery = query.trim();
    if (!nextQuery) {
      setItems([]);
      setLoading(false);
      setError("");
      return;
    }

    let cancelled = false;
    setLoading(true);
    const timer = window.setTimeout(() => {
      void client.searchWorkspace(botAlias, nextQuery, 100)
        .then((result) => {
          if (!cancelled) {
            setItems(result.items);
            setError("");
          }
        })
        .catch((caught) => {
          if (!cancelled) {
            setItems([]);
            setError(caught instanceof Error ? caught.message : "搜索失败");
          }
        })
        .finally(() => {
          if (!cancelled) {
            setLoading(false);
          }
        });
    }, 180);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [botAlias, client, query]);

  return (
    <section className="flex h-full min-h-0 flex-col bg-[var(--surface)]">
      <div className="border-b border-[var(--border)] px-3 py-3">
        <label className="text-xs font-semibold uppercase tracking-normal text-[var(--muted)]" htmlFor="workspace-full-text-search">
          搜索
        </label>
        <div className="mt-2 flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-strong)] px-2">
          <Search className="h-4 w-4 shrink-0 text-[var(--muted)]" />
          <input
            id="workspace-full-text-search"
            aria-label="全文搜索"
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="min-w-0 flex-1 bg-transparent py-2 text-sm text-[var(--text)] outline-none placeholder:text-[var(--muted)]"
            placeholder="关键词"
          />
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto py-1">
        {loading ? <div className="px-3 py-3 text-sm text-[var(--muted)]">搜索中...</div> : null}
        {error ? <div className="px-3 py-3 text-sm text-red-600">{error}</div> : null}
        {!loading && !error && query.trim() && items.length === 0 ? (
          <div className="px-3 py-3 text-sm text-[var(--muted)]">无匹配结果</div>
        ) : null}
        {items.map((item) => (
          <button
            key={`${item.path}:${item.line}:${item.column}:${item.preview}`}
            type="button"
            aria-label={`打开 ${item.path} 第 ${item.line} 行`}
            onClick={() => void onOpenFile(item.path, item.line)}
            className="flex w-full min-w-0 flex-col gap-1 border-b border-[var(--border)] px-3 py-2 text-left hover:bg-[var(--surface-strong)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent)]"
          >
            <span className="truncate font-mono text-xs text-[var(--muted)]">
              {item.path}:{item.line}:{item.column}
            </span>
            <span className="line-clamp-2 text-sm text-[var(--text)]">{item.preview}</span>
          </button>
        ))}
      </div>
    </section>
  );
}
