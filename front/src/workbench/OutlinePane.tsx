import { ListTree } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { CodeDocumentSymbol, WorkspaceOutlineItem } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { DocumentSymbolIcon, documentSymbolKindLabel } from "./documentSymbolKinds";
import { useDocumentSymbols } from "./useDocumentSymbols";
import type { EditorTab } from "./workbenchTypes";

type Props = {
  botAlias: string;
  client: WebBotClient;
  activeFilePath: string;
  /** The open document; with a language server its live text drives the outline. */
  activeTab?: EditorTab | null;
  languageFeaturesEnabled?: boolean;
  languageFeatureRefreshKey?: string;
  onOpenFile: (path: string, line?: number, column?: number) => void | Promise<void>;
};

type OutlineEntry = {
  name: string;
  detail: string;
  kind: string;
  line: number;
  column: number;
  children: OutlineEntry[];
};

function fromSymbols(symbols: readonly CodeDocumentSymbol[]): OutlineEntry[] {
  return symbols.map((symbol) => ({
    name: symbol.name,
    detail: symbol.detail,
    kind: symbol.kind,
    line: symbol.selectionRange.start.line,
    column: symbol.selectionRange.start.column,
    children: fromSymbols(symbol.children),
  }));
}

/** The file-based outline lists headings flat with a level; nest them like symbols. */
function fromOutlineItems(items: readonly WorkspaceOutlineItem[]): OutlineEntry[] {
  const roots: OutlineEntry[] = [];
  const stack: Array<{ level: number; entry: OutlineEntry }> = [];
  for (const item of items) {
    const entry: OutlineEntry = {
      name: item.name,
      detail: "",
      kind: item.kind,
      line: item.line,
      column: 1,
      children: fromOutlineItems(Array.isArray(item.children) ? item.children : []),
    };
    const level = typeof item.level === "number" && item.level > 0 ? item.level : 0;
    if (level === 0) {
      stack.length = 0;
      roots.push(entry);
      continue;
    }
    while (stack.length > 0 && stack[stack.length - 1].level >= level) stack.pop();
    const parent = stack[stack.length - 1]?.entry;
    (parent ? parent.children : roots).push(entry);
    stack.push({ level, entry });
  }
  return roots;
}

function OutlineItems({
  items,
  depth,
  activeFilePath,
  onOpenFile,
}: {
  items: OutlineEntry[];
  depth: number;
  activeFilePath: string;
  onOpenFile: Props["onOpenFile"];
}) {
  return (
    <>
      {items.map((item, index) => (
        <div key={`${item.kind}:${item.name}:${item.line}:${depth}:${index}`}>
          <button
            type="button"
            aria-label={`${item.name} ${item.kind} 第 ${item.line} 行`}
            title={item.detail ? `${item.name} ${item.detail}` : undefined}
            onClick={() => void onOpenFile(activeFilePath, item.line, item.column)}
            className="flex w-full min-w-0 items-center justify-between gap-2 px-3 py-1.5 text-left hover:bg-[var(--surface-strong)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent)]"
            style={{ paddingLeft: `${12 + depth * 14}px` }}
          >
            <span className="flex min-w-0 items-center gap-1.5">
              <DocumentSymbolIcon kind={item.kind} />
              <span className="min-w-0 truncate text-sm text-[var(--text)]">{item.name}</span>
              {item.detail ? <span className="min-w-0 truncate text-xs text-[var(--muted)]">{item.detail}</span> : null}
            </span>
            <span className="shrink-0 text-xs text-[var(--muted)]">{documentSymbolKindLabel(item.kind)} · {item.line}</span>
          </button>
          {item.children.length > 0 ? (
            <OutlineItems
              items={item.children}
              depth={depth + 1}
              activeFilePath={activeFilePath}
              onOpenFile={onOpenFile}
            />
          ) : null}
        </div>
      ))}
    </>
  );
}

export function OutlinePane({
  botAlias,
  client,
  activeFilePath,
  activeTab = null,
  languageFeaturesEnabled = false,
  languageFeatureRefreshKey = "",
  onOpenFile,
}: Props) {
  const [fileItems, setFileItems] = useState<WorkspaceOutlineItem[]>([]);
  const [fileLoading, setFileLoading] = useState(false);
  const [error, setError] = useState("");
  const symbolTab = activeTab && activeTab.path === activeFilePath ? activeTab : null;
  const symbols = useDocumentSymbols(client, botAlias, symbolTab, languageFeaturesEnabled, languageFeatureRefreshKey);
  // The saved-file outline covers languages without a server (Python by AST, Markdown headings).
  const useFileOutline = Boolean(activeFilePath) && (symbols.status === "idle" || symbols.status === "unavailable")
    && !(languageFeaturesEnabled && symbolTab?.loading);

  useEffect(() => {
    if (!activeFilePath || !useFileOutline) {
      setFileItems([]);
      setFileLoading(false);
      setError("");
      return;
    }

    let cancelled = false;
    setFileLoading(true);
    void client.getWorkspaceOutline(botAlias, activeFilePath)
      .then((result) => {
        if (!cancelled) {
          setFileItems(result.items);
          setError("");
        }
      })
      .catch((caught) => {
        if (!cancelled) {
          setFileItems([]);
          setError(caught instanceof Error ? caught.message : "读取大纲失败");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setFileLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [activeFilePath, botAlias, client, useFileOutline]);

  const items = useMemo(
    () => (useFileOutline ? fromOutlineItems(fileItems) : fromSymbols(symbols.symbols)),
    [fileItems, symbols.symbols, useFileOutline],
  );
  const loading = useFileOutline ? fileLoading : symbols.status === "loading";

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
        {error ? <div className="px-3 py-3 text-sm text-[var(--feedback-error-text-strong)]">{error}</div> : null}
        {!loading && !error && activeFilePath && items.length === 0 ? (
          <div className="px-3 py-3 text-sm text-[var(--muted)]">无符号</div>
        ) : null}
        {!activeFilePath ? <div className="px-3 py-3 text-sm text-[var(--muted)]">未打开文件</div> : null}
        <OutlineItems
          items={items}
          depth={0}
          activeFilePath={activeFilePath}
          onOpenFile={onOpenFile}
        />
      </div>
    </section>
  );
}
