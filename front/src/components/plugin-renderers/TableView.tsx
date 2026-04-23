import { startTransition, useDeferredValue, useEffect, useRef, useState } from "react";
import type { PluginAction, PluginRenderResult, TableColumn, TableSort, TableWindowPayload } from "../../services/types";
import type { WebBotClient } from "../../services/webBotClient";
import { PluginActionBar } from "./PluginActionBar";

type Props = {
  botAlias: string;
  client: WebBotClient;
  view: Extract<PluginRenderResult, { renderer: "table" }>;
  onRunAction?: (action: PluginAction, payload?: Record<string, unknown>) => void | Promise<void>;
};

function renderCellValue(value: unknown) {
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(3).replace(/\.?0+$/, "");
  }
  if (typeof value === "boolean") {
    return value ? "是" : "否";
  }
  if (value === null || typeof value === "undefined") {
    return "";
  }
  return String(value);
}

function nextSort(column: TableColumn, current?: TableSort): TableSort | undefined {
  if (!column.sortable) {
    return current;
  }
  if (!current || current.columnId !== column.id) {
    return { columnId: column.id, direction: "asc" };
  }
  if (current.direction === "asc") {
    return { columnId: column.id, direction: "desc" };
  }
  return undefined;
}

export function TableView({ botAlias, client, view, onRunAction }: Props) {
  const session = view.mode === "session" ? view : null;
  const summary = view.mode === "session"
    ? view.summary
    : {
        columns: view.payload.columns,
        totalRows: view.payload.rows.length,
        defaultPageSize: view.payload.rows.length || 100,
        actions: view.payload.actions,
      };
  const initialWindow: TableWindowPayload = view.mode === "session"
    ? view.initialWindow
    : {
        offset: 0,
        limit: view.payload.rows.length || summary.defaultPageSize,
        totalRows: view.payload.rows.length,
        rows: view.payload.rows,
      };

  const [windowState, setWindowState] = useState<TableWindowPayload>(initialWindow);
  const [offset, setOffset] = useState(Number(initialWindow.offset || 0));
  const [sort, setSort] = useState<TableSort | undefined>(initialWindow.appliedSort);
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
  const requestIdRef = useRef(0);
  const pageSize = Math.max(1, Number(initialWindow.limit || summary.defaultPageSize || 100));
  const totalRows = Number(windowState.totalRows || summary.totalRows || 0);
  const pageIndex = Math.floor(offset / pageSize) + 1;
  const pageCount = Math.max(1, Math.ceil(totalRows / pageSize));

  useEffect(() => {
    setWindowState(initialWindow);
    setOffset(Number(initialWindow.offset || 0));
    setSort(initialWindow.appliedSort);
    setQuery("");
  }, [initialWindow, view.sessionId]);

  useEffect(() => {
    if (!session) {
      return;
    }
    const controller = new AbortController();
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    void client.queryPluginViewWindow(
      botAlias,
      view.pluginId,
      view.sessionId,
      {
        offset,
        limit: pageSize,
        sort,
        query: deferredQuery,
      },
      controller.signal,
    ).then((payload) => {
      if (requestIdRef.current !== requestId) {
        return;
      }
      startTransition(() => {
        setWindowState(payload as TableWindowPayload);
      });
    }).catch((error) => {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      throw error;
    });
    return () => controller.abort();
  }, [botAlias, client, deferredQuery, offset, pageSize, session, sort, view.pluginId, view.sessionId]);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <PluginActionBar actions={summary.actions} onRunAction={(action) => onRunAction?.(action)} />

      <div className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-3 py-2">
        <div className="text-sm text-[var(--muted)]">
          第 {pageIndex}/{pageCount} 页 · 共 {totalRows} 行
        </div>
        {session ? (
          <label className="flex items-center gap-2 text-sm text-[var(--muted)]">
            搜索
            <input
              value={query}
              onChange={(event) => {
                setOffset(0);
                setQuery(event.currentTarget.value);
              }}
              className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-1.5 text-sm text-[var(--text)]"
            />
          </label>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 z-10 bg-[var(--surface)]">
            <tr className="border-b border-[var(--border)]">
              {summary.columns.map((column) => (
                <th
                  key={column.id}
                  className="px-3 py-2 text-left font-medium text-[var(--text)]"
                  style={{ textAlign: column.align || "left" }}
                >
                  <button
                    type="button"
                    disabled={!column.sortable}
                    onClick={() => {
                      const next = nextSort(column, sort);
                      setOffset(0);
                      setSort(next);
                    }}
                    className="inline-flex items-center gap-1 disabled:cursor-default"
                  >
                    <span>{column.title}</span>
                    {sort?.columnId === column.id ? (
                      <span className="text-xs text-[var(--muted)]">{sort.direction === "asc" ? "↑" : "↓"}</span>
                    ) : null}
                  </button>
                </th>
              ))}
              <th className="w-1 px-3 py-2 text-right text-[var(--muted)]">动作</th>
            </tr>
          </thead>
          <tbody>
            {windowState.rows.map((row) => (
              <tr key={row.id} className="border-b border-[var(--border)]/70">
                {summary.columns.map((column) => (
                  <td
                    key={`${row.id}-${column.id}`}
                    className="px-3 py-2 text-[var(--text)]"
                    style={{ textAlign: column.align || "left" }}
                  >
                    {renderCellValue(row.cells[column.id])}
                  </td>
                ))}
                <td className="px-3 py-2 text-right">
                  <div className="flex justify-end gap-2">
                    {(row.actions || []).map((action) => (
                      <button
                        key={`${row.id}-${action.id}`}
                        type="button"
                        disabled={action.disabled}
                        onClick={() => onRunAction?.(action, { rowId: row.id })}
                        className="rounded-lg border border-[var(--border)] px-2 py-1 text-xs text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-60"
                      >
                        {action.label}
                      </button>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
            {windowState.rows.length === 0 ? (
              <tr>
                <td colSpan={summary.columns.length + 1} className="px-3 py-8 text-center text-sm text-[var(--muted)]">
                  无结果
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      {session ? (
        <div className="flex items-center justify-end gap-2 border-t border-[var(--border)] px-3 py-2">
          <button
            type="button"
            onClick={() => setOffset((current) => Math.max(0, current - pageSize))}
            disabled={offset <= 0}
            className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-60"
          >
            上一页
          </button>
          <button
            type="button"
            onClick={() => setOffset((current) => current + pageSize >= totalRows ? current : current + pageSize)}
            disabled={offset + pageSize >= totalRows}
            className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-60"
          >
            下一页
          </button>
        </div>
      ) : null}
    </div>
  );
}
