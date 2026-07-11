import { startTransition, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import type { PluginAction, PluginRenderResult, TableColumn, TableRow, TableSort, TableWindowPayload } from "../../services/types";
import type { WebBotClient } from "../../services/webBotClient";
import { DynamicVirtualList } from "../virtual/DynamicVirtualList";
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

function compareCellValues(left: unknown, right: unknown) {
  if (typeof left === "number" && typeof right === "number") {
    return left - right;
  }
  return renderCellValue(left).localeCompare(renderCellValue(right), "zh-CN", {
    numeric: true,
    sensitivity: "base",
  });
}

export function TableView({ botAlias, client, view, onRunAction }: Props) {
  const session = view.mode === "session" ? view : null;
  const snapshot = view.mode === "snapshot" ? view : null;
  const summary = useMemo(
    () => (view.mode === "session"
      ? view.summary
      : {
          columns: view.payload.columns,
          totalRows: view.payload.rows.length,
          defaultPageSize: view.payload.rows.length || 100,
          actions: view.payload.actions,
        }),
    [view],
  );
  const initialWindow: TableWindowPayload = useMemo(
    () => (view.mode === "session"
      ? view.initialWindow
      : {
          offset: 0,
          limit: view.payload.rows.length || summary.defaultPageSize,
          totalRows: view.payload.rows.length,
          rows: view.payload.rows,
        }),
    [summary.defaultPageSize, view],
  );

  const [windowState, setWindowState] = useState<TableWindowPayload>(initialWindow);
  const [offset, setOffset] = useState(Number(initialWindow.offset || 0));
  const [sort, setSort] = useState<TableSort | undefined>(initialWindow.appliedSort);
  const [query, setQuery] = useState("");
  const [windowError, setWindowError] = useState("");
  const deferredQuery = useDeferredValue(query);
  const requestIdRef = useRef(0);
  const pageSize = Math.max(1, Math.min(500, Number(initialWindow.limit || summary.defaultPageSize || 100)));
  const snapshotRows = useMemo<TableRow[]>(() => {
    if (!snapshot) {
      return [];
    }
    const normalizedQuery = deferredQuery.trim().toLocaleLowerCase();
    const filtered = normalizedQuery
      ? snapshot.payload.rows.filter((row) => summary.columns.some((column) => (
          renderCellValue(row.cells[column.id]).toLocaleLowerCase().includes(normalizedQuery)
        )))
      : snapshot.payload.rows;
    if (!sort) {
      return filtered;
    }
    const direction = sort.direction === "desc" ? -1 : 1;
    return [...filtered].sort((left, right) => (
      compareCellValues(left.cells[sort.columnId], right.cells[sort.columnId]) * direction
    ));
  }, [deferredQuery, snapshot, sort, summary.columns]);
  const displayRows = session ? windowState.rows : snapshotRows;
  const totalRows = session
    ? Number(windowState.totalRows || summary.totalRows || 0)
    : snapshotRows.length;
  const pageIndex = Math.floor(offset / pageSize) + 1;
  const pageCount = Math.max(1, Math.ceil(totalRows / pageSize));

  useEffect(() => {
    setWindowState(initialWindow);
    setOffset(Number(initialWindow.offset || 0));
    setSort(initialWindow.appliedSort);
    setQuery("");
    setWindowError("");
  }, [initialWindow, session?.sessionId]);

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
      session.sessionId,
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
        setWindowError("");
        setWindowState(payload as TableWindowPayload);
      });
    }).catch((error) => {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      if (requestIdRef.current !== requestId) {
        return;
      }
      setWindowError(error instanceof Error ? error.message : "加载窗口失败");
    });
    return () => controller.abort();
  }, [botAlias, client, deferredQuery, offset, pageSize, session, sort, view.pluginId]);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <PluginActionBar actions={summary.actions} onRunAction={(action) => onRunAction?.(action)} />

      <div className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-3 py-2">
        <div className="text-sm text-[var(--muted)]">
          {session ? `第 ${pageIndex}/${pageCount} 页 · ` : ""}共 {totalRows} 行
        </div>
        {windowError ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {windowError}
          </div>
        ) : null}
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
      </div>

      {snapshot && snapshot.payload.rows.length > 5000 ? (
        <div className="border-b border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          当前快照包含 {snapshot.payload.rows.length} 行；建议插件改用 session/heavy 视图降低传输成本。
        </div>
      ) : null}

      <div className={displayRows.length > 100 ? "min-h-0 flex-1 overflow-hidden" : "min-h-0 flex-1 overflow-auto"}>
        {displayRows.length > 100 ? (
          <div role="table" aria-rowcount={displayRows.length} className="flex h-full min-h-0 min-w-full flex-col text-sm">
            <div
              role="row"
              className="z-10 grid flex-none border-b border-[var(--border)] bg-[var(--surface)]"
              style={{ gridTemplateColumns: `repeat(${summary.columns.length}, minmax(120px, 1fr)) minmax(72px, auto)` }}
            >
              {summary.columns.map((column) => (
                <div key={column.id} role="columnheader" className="px-3 py-2 font-medium text-[var(--text)]">
                  <button
                    type="button"
                    disabled={!column.sortable}
                    onClick={() => {
                      setOffset(0);
                      setSort(nextSort(column, sort));
                    }}
                    className="inline-flex items-center gap-1 disabled:cursor-default"
                  >
                    <span>{column.title}</span>
                    {sort?.columnId === column.id ? <span className="text-xs text-[var(--muted)]">{sort.direction === "asc" ? "↑" : "↓"}</span> : null}
                  </button>
                </div>
              ))}
              <div role="columnheader" className="px-3 py-2 text-right text-[var(--muted)]">动作</div>
            </div>
            <DynamicVirtualList
              items={displayRows}
              getKey={(row) => row.id}
              renderItem={(row) => (
                <div
                  role="row"
                  data-testid="plugin-table-row"
                  className="grid border-b border-[var(--border)]/70"
                  style={{ gridTemplateColumns: `repeat(${summary.columns.length}, minmax(120px, 1fr)) minmax(72px, auto)` }}
                >
                  {summary.columns.map((column) => (
                    <div key={`${row.id}-${column.id}`} role="cell" className="min-w-0 break-words px-3 py-2 text-[var(--text)]">
                      {renderCellValue(row.cells[column.id])}
                    </div>
                  ))}
                  <div role="cell" className="px-3 py-2 text-right">
                    {(row.actions || []).map((action) => (
                      <button
                        key={`${row.id}-${action.id}`}
                        type="button"
                        disabled={action.disabled}
                        onClick={() => onRunAction?.(action, { rowId: row.id })}
                        className="ml-2 rounded-lg border border-[var(--border)] px-2 py-1 text-xs text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-60"
                      >
                        {action.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              estimateHeight={40}
              overscan={8}
              dataTestId="virtualized-plugin-table"
              className="min-h-0 flex-1 overflow-auto"
            />
          </div>
        ) : (
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
            {displayRows.map((row) => (
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
            {displayRows.length === 0 ? (
              <tr>
                <td colSpan={summary.columns.length + 1} className="px-3 py-8 text-center text-sm text-[var(--muted)]">
                  无结果
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
        )}
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
