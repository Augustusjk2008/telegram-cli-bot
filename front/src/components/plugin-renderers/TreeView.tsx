import { startTransition, useDeferredValue, useEffect, useRef, useState } from "react";
import type { PluginAction, PluginRenderResult, TreeNode, TreeViewSummary, TreeWindowPayload } from "../../services/types";
import type { WebBotClient } from "../../services/webBotClient";
import { VirtualList } from "../virtual/VirtualList";
import { PluginActionBar } from "./PluginActionBar";

type Props = {
  botAlias: string;
  client: WebBotClient;
  view: Extract<PluginRenderResult, { renderer: "tree" }>;
  onRunAction?: (action: PluginAction, payload?: Record<string, unknown>) => void | Promise<void>;
};

type VisibleRow =
  | { type: "node"; node: TreeNode; depth: number }
  | { type: "status"; node: TreeNode; depth: number; loading: boolean; error: string };

function nodeChildren(nodes: TreeNode[], nodeId: string, children: TreeNode[]): TreeNode[] {
  return nodes.map((node) => {
    if (node.id === nodeId) {
      return {
        ...node,
        hasChildren: children.length > 0 || nodeHasChildren(node),
        expandable: children.length > 0 || nodeHasChildren(node),
        children,
      };
    }
    if (!node.children?.length) {
      return node;
    }
    return {
      ...node,
      children: nodeChildren(node.children, nodeId, children),
    };
  });
}

function getWindowNodes(payload: TreeWindowPayload | Record<string, unknown>, fallback: TreeNode[] = []): TreeNode[] {
  const nodes = Array.isArray(payload.nodes)
    ? payload.nodes
    : Array.isArray(payload.roots)
      ? payload.roots
      : fallback;
  return nodes;
}

function nodeHasChildren(node: TreeNode) {
  return Boolean(node.hasChildren ?? node.expandable ?? node.children?.length);
}

function nodeSecondaryText(node: TreeNode) {
  return node.secondaryText || node.description || "";
}

function nodeBadges(node: TreeNode) {
  if (node.badges?.length) {
    return node.badges;
  }
  if (node.badge) {
    return [{ text: node.badge }];
  }
  return [];
}

function kindMarker(kind?: TreeNode["kind"]) {
  switch (kind) {
    case "folder":
      return { text: "D", className: "border-amber-300 bg-amber-50 text-amber-700" };
    case "file":
      return { text: "F", className: "border-slate-300 bg-slate-50 text-slate-700" };
    case "class":
      return { text: "C", className: "border-sky-300 bg-sky-50 text-sky-700" };
    case "function":
      return { text: "fn", className: "border-emerald-300 bg-emerald-50 text-emerald-700" };
    case "method":
      return { text: "m", className: "border-teal-300 bg-teal-50 text-teal-700" };
    case "heading":
      return { text: "#", className: "border-violet-300 bg-violet-50 text-violet-700" };
    default:
      return { text: "S", className: "border-zinc-300 bg-zinc-50 text-zinc-700" };
  }
}

function getPrimaryAction(node: TreeNode) {
  return (node.actions || []).find((action) => !action.disabled);
}

function flattenVisibleNodes(
  nodes: TreeNode[],
  expanded: Record<string, boolean>,
  loadingByNode: Record<string, boolean>,
  errorByNode: Record<string, string>,
  forceExpandLoadedChildren: boolean,
  depth = 0,
): VisibleRow[] {
  const rows: VisibleRow[] = [];
  for (const node of nodes) {
    rows.push({ type: "node", node, depth });
    const isExpanded = expanded[node.id] || (forceExpandLoadedChildren && !!node.children?.length);
    if (!isExpanded) {
      continue;
    }
    if (loadingByNode[node.id]) {
      rows.push({ type: "status", node, depth: depth + 1, loading: true, error: "" });
    } else if (errorByNode[node.id]) {
      rows.push({ type: "status", node, depth: depth + 1, loading: false, error: errorByNode[node.id] || "" });
    }
    if (node.children?.length) {
      rows.push(...flattenVisibleNodes(node.children, expanded, loadingByNode, errorByNode, forceExpandLoadedChildren, depth + 1));
    }
  }
  return rows;
}

function filterLocalTree(nodes: TreeNode[], rawQuery: string): TreeNode[] {
  const query = rawQuery.trim().toLowerCase();
  if (!query) {
    return nodes;
  }
  return nodes.flatMap((node) => {
    const children = filterLocalTree(node.children || [], rawQuery);
    const searchableText = [
      node.label,
      nodeSecondaryText(node),
      node.kind || "",
    ].join(" ").toLowerCase();
    if (!searchableText.includes(query) && children.length === 0) {
      return [];
    }
    return [{
      ...node,
      children,
    }];
  });
}

function findNodeLabel(nodes: TreeNode[], nodeId: string): string {
  for (const node of nodes) {
    if (node.id === nodeId) {
      return node.label;
    }
    const childLabel = node.children?.length ? findNodeLabel(node.children, nodeId) : "";
    if (childLabel) {
      return childLabel;
    }
  }
  return "";
}

export function TreeView({ botAlias, client, view, onRunAction }: Props) {
  const session = view.mode === "session" ? view : null;
  const summary: TreeViewSummary = view.mode === "session"
    ? view.summary
    : {
        roots: view.payload.roots,
        actions: view.payload.actions,
        searchable: view.payload.searchable ?? true,
        searchPlaceholder: view.payload.searchPlaceholder,
        statsText: view.payload.statsText,
        emptySearchText: view.payload.emptySearchText,
      };
  const initialRoots = view.mode === "session"
    ? getWindowNodes(view.initialWindow, summary.roots || [])
    : view.payload.roots || [];
  const [treeRoots, setTreeRoots] = useState<TreeNode[]>(initialRoots);
  const [searchRoots, setSearchRoots] = useState<TreeNode[] | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [statsText, setStatsText] = useState(summary.statsText || "");
  const [loadingByNode, setLoadingByNode] = useState<Record<string, boolean>>({});
  const [errorByNode, setErrorByNode] = useState<Record<string, string>>({});
  const deferredQuery = useDeferredValue(query);
  const searchRequestRef = useRef(0);
  const childrenRequestRef = useRef<Record<string, number>>({});
  const treeEpochRef = useRef(0);

  useEffect(() => {
    setTreeRoots(initialRoots);
    setSearchRoots(null);
    setExpanded({});
    setQuery("");
    setSearching(false);
    setSearchError("");
    setStatsText(summary.statsText || "");
    setLoadingByNode({});
    setErrorByNode({});
    searchRequestRef.current = 0;
    childrenRequestRef.current = {};
    treeEpochRef.current = 0;
  }, [initialRoots, summary.statsText, view.pluginId, session?.sessionId]);

  useEffect(() => {
    if (!session) {
      return;
    }
    const nextQuery = deferredQuery.trim();
    treeEpochRef.current += 1;
    searchRequestRef.current += 1;
    const requestId = searchRequestRef.current;

    if (!nextQuery) {
      startTransition(() => {
        setSearchRoots(null);
        setSearching(false);
        setSearchError("");
        setStatsText(summary.statsText || "");
      });
      return;
    }

    const controller = new AbortController();
    setSearching(true);
    setSearchError("");

    void client.queryPluginViewWindow(
      botAlias,
      view.pluginId,
      session.sessionId,
      {
        op: "search",
        query: nextQuery,
      },
      controller.signal,
    ).then((payload) => {
      if (searchRequestRef.current !== requestId) {
        return;
      }
      const next = payload as TreeWindowPayload;
      startTransition(() => {
        setSearchRoots(getWindowNodes(next));
        setStatsText(next.statsText || "");
        setSearching(false);
      });
    }).catch((error) => {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      if (searchRequestRef.current !== requestId) {
        return;
      }
      setSearching(false);
      setSearchRoots([]);
      setSearchError(error instanceof Error && error.message ? error.message : "搜索失败");
    });

    return () => controller.abort();
  }, [botAlias, client, deferredQuery, session, summary.statsText, view.pluginId]);

  async function loadChildren(node: TreeNode) {
    if (!session || !nodeHasChildren(node)) {
      return;
    }
    const requestId = (childrenRequestRef.current[node.id] || 0) + 1;
    childrenRequestRef.current[node.id] = requestId;
    const epoch = treeEpochRef.current;
    setLoadingByNode((current) => ({ ...current, [node.id]: true }));
    setErrorByNode((current) => ({ ...current, [node.id]: "" }));
    try {
      const payload = await client.queryPluginViewWindow(botAlias, view.pluginId, session.sessionId, {
        op: "children",
        nodeId: node.id,
      });
      if (childrenRequestRef.current[node.id] !== requestId || treeEpochRef.current !== epoch) {
        return;
      }
      const next = payload as TreeWindowPayload;
      startTransition(() => {
        setTreeRoots((current) => nodeChildren(current, node.id, getWindowNodes(next)));
      });
    } catch (error) {
      if (childrenRequestRef.current[node.id] !== requestId || treeEpochRef.current !== epoch) {
        return;
      }
      setErrorByNode((current) => ({
        ...current,
        [node.id]: error instanceof Error && error.message ? error.message : "加载子节点失败",
      }));
    } finally {
      if (childrenRequestRef.current[node.id] === requestId) {
        setLoadingByNode((current) => ({ ...current, [node.id]: false }));
      }
    }
  }

  async function toggleNode(node: TreeNode) {
    const nextExpanded = !expanded[node.id];
    setExpanded((current) => ({ ...current, [node.id]: nextExpanded }));
    if (!nextExpanded || query.trim() || node.children?.length) {
      return;
    }
    await loadChildren(node);
  }

  function runNodeAction(action: PluginAction, node: TreeNode) {
    return onRunAction?.(action, {
      nodeId: node.id,
      ...(node.payload || {}),
    });
  }

  function handleNodeLabelClick(node: TreeNode) {
    const primaryAction = getPrimaryAction(node);
    if (primaryAction) {
      void runNodeAction(primaryAction, node);
      return;
    }
    if (nodeHasChildren(node)) {
      void toggleNode(node);
    }
  }

  function handleToolbarAction(action: PluginAction) {
    if (action.id === "collapse-all") {
      setExpanded({});
      return;
    }
    void onRunAction?.(action);
  }

  const queryActive = deferredQuery.trim().length > 0;
  const activeRoots = session
    ? (queryActive ? (searchRoots || []) : treeRoots)
    : (queryActive ? filterLocalTree(treeRoots, deferredQuery) : treeRoots);
  const visibleRows = flattenVisibleNodes(activeRoots, expanded, loadingByNode, errorByNode, queryActive);
  const loadingNodeIds = Object.keys(loadingByNode).filter((nodeId) => loadingByNode[nodeId]);
  const expandingText = loadingNodeIds.length === 1
    ? `正在展开 ${findNodeLabel(activeRoots, loadingNodeIds[0]) || "节点"}...`
    : loadingNodeIds.length > 1
      ? `正在展开 ${loadingNodeIds.length} 个节点...`
      : "";
  const emptyText = queryActive
    ? (searchError || summary.emptySearchText || "未找到匹配目录、文件、符号")
    : "无结果";

  function renderVisibleRow(row: VisibleRow) {
    if (row.type === "status") {
      return (
        <div className="flex h-full items-center border-b border-[var(--border)]/70 px-3 text-sm text-[var(--muted)]">
          <div style={{ paddingLeft: row.depth * 16 + 28 }}>
            {row.loading ? `正在展开 ${row.node.label}...` : (
              <div className="flex items-center gap-2">
                <span>{row.error || "加载失败"}</span>
                <button
                  type="button"
                  onClick={() => void loadChildren(row.node)}
                  className="rounded border border-[var(--border)] px-2 py-0.5 text-xs text-[var(--text)] hover:bg-[var(--surface-strong)]"
                >
                  重试
                </button>
              </div>
            )}
          </div>
        </div>
      );
    }

    const { node, depth } = row;
    const isExpanded = !!expanded[node.id] || (queryActive && !!node.children?.length);
    const canExpand = nodeHasChildren(node);
    const marker = kindMarker(node.kind);
    const primaryAction = getPrimaryAction(node);
    const secondary = nodeSecondaryText(node);
    const badges = nodeBadges(node);

    return (
      <div className="group flex h-full items-center border-b border-[var(--border)]/70 px-3 text-sm">
        <div className="flex w-full items-start justify-between gap-3">
          <div className="flex min-w-0 flex-1 items-start gap-2" style={{ paddingLeft: depth * 16 }}>
            <button
              type="button"
              onClick={() => void toggleNode(node)}
              className="mt-0.5 h-6 w-6 shrink-0 rounded border border-[var(--border)] text-xs text-[var(--muted)] disabled:opacity-50"
              disabled={!canExpand}
              aria-label={isExpanded ? `折叠 ${node.label}` : `展开 ${node.label}`}
            >
              {canExpand ? (isExpanded ? "−" : "+") : "·"}
            </button>
            <span className={`mt-0.5 inline-flex h-6 min-w-6 shrink-0 items-center justify-center rounded border px-1.5 text-[10px] font-semibold uppercase ${marker.className}`}>
              {marker.text}
            </span>
            <div className="min-w-0 flex-1">
              <button
                type="button"
                onClick={() => handleNodeLabelClick(node)}
                className="min-w-0 max-w-full text-left text-[var(--text)] hover:text-[var(--accent)]"
                aria-label={primaryAction ? `${primaryAction.label} ${node.label}` : node.label}
              >
                <span className="truncate">{node.label}</span>
              </button>
              {secondary ? <div className="truncate text-xs text-[var(--muted)]">{secondary}</div> : null}
              {badges.length > 0 ? (
                <div className="mt-1 flex flex-wrap items-center gap-1">
                  {badges.map((badge) => (
                    <span
                      key={`${node.id}-${badge.text}`}
                      className="rounded-full bg-[var(--surface-strong)] px-2 py-0.5 text-[11px] text-[var(--muted)]"
                    >
                      {badge.text}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
          {(node.actions || []).length > 0 ? (
            <div className="flex shrink-0 items-center gap-1">
              {(node.actions || []).map((action) => (
                <button
                  key={`${node.id}-${action.id}`}
                  type="button"
                  disabled={action.disabled}
                  onClick={() => void runNodeAction(action, node)}
                  className="rounded border border-[var(--border)] px-2 py-1 text-xs text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-60"
                  aria-label={action.label}
                >
                  {action.label}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <PluginActionBar actions={summary.actions} onRunAction={handleToolbarAction} />
      <div className="border-b border-[var(--border)] px-3 py-2">
        <div className="flex flex-wrap items-center gap-3">
          {summary.searchable !== false ? (
            <label className="flex min-w-[220px] flex-1 items-center gap-2 text-sm text-[var(--muted)]">
              搜索
              <input
                value={query}
                onChange={(event) => setQuery(event.currentTarget.value)}
                placeholder={summary.searchPlaceholder || "搜目录、文件、符号"}
                className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-1.5 text-sm text-[var(--text)]"
              />
            </label>
          ) : null}
          {statsText ? <div className="text-xs text-[var(--muted)]">{statsText}</div> : null}
          {searching ? <div className="text-xs text-[var(--muted)]">搜索中...</div> : null}
          {expandingText ? <div className="text-xs text-[var(--muted)]">{expandingText}</div> : null}
        </div>
      </div>
      <div className="min-h-0 flex-1">
        {visibleRows.length > 0 ? (
          <VirtualList
            items={visibleRows}
            rowHeight={72}
            className="h-full"
            dataTestId="plugin-tree-virtual-list"
            getKey={(row) => row.type === "status" ? `${row.node.id}-status` : row.node.id}
            renderRow={(row) => renderVisibleRow(row)}
          />
        ) : (
          <div className="px-3 py-8 text-center text-sm text-[var(--muted)]">{emptyText}</div>
        )}
      </div>
    </div>
  );
}
