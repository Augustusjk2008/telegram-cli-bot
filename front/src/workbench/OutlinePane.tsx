import { ListTree } from "lucide-react";
import { useEffect, useState } from "react";
import type { WorkspaceOutlineItem } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  botAlias: string;
  client: WebBotClient;
  activeFilePath: string;
  onOpenFile: (path: string, line?: number) => void | Promise<void>;
};

const KIND_LABEL: Record<WorkspaceOutlineItem["kind"], string> = {
  class: "类",
  function: "函数",
  method: "方法",
  heading: "标题",
};

export function OutlinePane({ botAlias, client, activeFilePath, onOpenFile }: Props) {
  const [items, setItems] = useState<WorkspaceOutlineItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!activeFilePath) {
      setItems([]);
      setLoading(false);
      setError("");
      return;
    }

    let cancelled = false;
    setLoading(true);
    void client.getWorkspaceOutline(botAlias, activeFilePath)
      .then((result) => {
        if (!cancelled) {
          setItems(result.items);
          setError("");
        }
      })
      .catch((caught) => {
        if (!cancelled) {
          setItems([]);
          setError(caught instanceof Error ? caught.message : "读取大纲失败");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [activeFilePath, botAlias, client]);

  return (
    <section className="flex h-full min-h-0 flex-col bg-[var(--surface)]">
      <div className="flex items-center gap-2 border-b border-[var(--border)] px-3 py-3">
        <ListTree className="h-4 w-4 text-[var(--muted)]" />
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-[var(--text)]">大纲</h2>
          <p className="truncate font-mono text-xs text-[var(--muted)]">{activeFilePath || "未打开文件"}</p>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto py-1">
        {loading ? <div className="px-3 py-3 text-sm text-[var(--muted)]">加载中...</div> : null}
        {error ? <div className="px-3 py-3 text-sm text-red-600">{error}</div> : null}
        {!loading && !error && activeFilePath && items.length === 0 ? (
          <div className="px-3 py-3 text-sm text-[var(--muted)]">无符号</div>
        ) : null}
        {!activeFilePath ? <div className="px-3 py-3 text-sm text-[var(--muted)]">未打开文件</div> : null}
        {items.map((item) => (
          <button
            key={`${item.kind}:${item.name}:${item.line}`}
            type="button"
            aria-label={`${item.name} ${item.kind} 第 ${item.line} 行`}
            onClick={() => void onOpenFile(activeFilePath, item.line)}
            className="flex w-full min-w-0 items-center justify-between gap-2 px-3 py-2 text-left hover:bg-[var(--surface-strong)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent)]"
          >
            <span className="min-w-0 truncate text-sm text-[var(--text)]">{item.name}</span>
            <span className="shrink-0 text-xs text-[var(--muted)]">{KIND_LABEL[item.kind]} · {item.line}</span>
          </button>
        ))}
      </div>
    </section>
  );
}
