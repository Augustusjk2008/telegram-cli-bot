import { Search, X } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { delightMotion, delightMotionStagger, premiumMotion, resolveMotionProps } from "../motion/premiumMotion";
import type { WorkspaceQuickOpenItem } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  open: boolean;
  botAlias: string;
  client: WebBotClient;
  onClose: () => void;
  onOpenFile: (path: string) => void | Promise<void>;
  disabled?: boolean;
};

function basename(path: string) {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

export function CommandPalette({ open, botAlias, client, onClose, onOpenFile, disabled = false }: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<WorkspaceQuickOpenItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    if (!open || disabled) {
      return;
    }
    setQuery("");
    setItems([]);
    setError("");
    window.setTimeout(() => inputRef.current?.focus(), 0);
  }, [disabled, open]);

  useEffect(() => {
    if (!open || disabled) {
      return;
    }
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
      void client.quickOpenWorkspace(botAlias, nextQuery, 50)
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
    }, 120);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [botAlias, client, disabled, open, query]);

  async function openPath(path: string) {
    if (disabled) {
      return;
    }
    await onOpenFile(path);
    onClose();
  }

  const firstPath = items[0]?.path || "";

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="fixed inset-0 z-50 bg-black/45 p-4 pt-[12vh]"
          onMouseDown={onClose}
          {...resolveMotionProps(premiumMotion.paletteBackdrop, reduceMotion)}
        >
          <motion.section
            role="dialog"
            aria-modal="true"
            aria-label="快速打开"
            className="mx-auto flex max-h-[70vh] w-full max-w-2xl flex-col overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-card)]"
            onMouseDown={(event) => event.stopPropagation()}
            {...resolveMotionProps(premiumMotion.palettePanel, reduceMotion)}
          >
            <div className="flex items-center gap-2 border-b border-[var(--border)] px-3 py-2">
              <div
                data-testid="quick-open-search-field"
                className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-transparent px-2 focus-within:border-[var(--accent-outline)] focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-[var(--accent-outline)]"
              >
                <Search className="h-4 w-4 shrink-0 text-[var(--muted)]" />
                <input
                  ref={inputRef}
                  aria-label="快速打开文件"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Escape") {
                      event.preventDefault();
                      onClose();
                    }
                    if (event.key === "Enter" && firstPath) {
                      event.preventDefault();
                      void openPath(firstPath);
                    }
                  }}
                  className="min-w-0 flex-1 bg-transparent py-2 text-sm text-[var(--text)] outline-none placeholder:text-[var(--muted)]"
                  placeholder="输入文件名"
                />
              </div>
              <button
                type="button"
                aria-label="关闭快速打开"
                onClick={onClose}
                className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)]"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="min-h-0 overflow-y-auto py-1">
              {loading ? <div className="px-3 py-3 text-sm text-[var(--muted)]">搜索中...</div> : null}
              {error ? <div className="px-3 py-3 text-sm text-red-600">{error}</div> : null}
              {!loading && !error && query.trim() && items.length === 0 ? (
                <div className="px-3 py-3 text-sm text-[var(--muted)]">无匹配文件</div>
              ) : null}
              {items.map((item, index) => {
                const animateIndex = Math.min(index, delightMotionStagger.maxAnimatedItems - 1);
                return (
                  <motion.button
                    key={item.path}
                    type="button"
                    aria-label={`打开 ${item.path}`}
                    onClick={() => void openPath(item.path)}
                    className="flex w-full min-w-0 flex-col gap-0.5 px-3 py-2 text-left hover:bg-[var(--surface-strong)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent)]"
                    data-first-match={index === 0 ? "true" : "false"}
                    {...resolveMotionProps({
                      ...delightMotion.paletteItem,
                      transition: {
                        ...delightMotion.paletteItem.transition,
                        delay: index < delightMotionStagger.maxAnimatedItems ? animateIndex * delightMotionStagger.itemDelaySeconds : 0,
                      },
                    }, reduceMotion)}
                  >
                    <span className="truncate text-sm font-medium text-[var(--text)]">{basename(item.path)}</span>
                    <span className="truncate font-mono text-xs text-[var(--muted)]">{item.path}</span>
                  </motion.button>
                );
              })}
            </div>
          </motion.section>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
