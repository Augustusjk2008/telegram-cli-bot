import { startTransition, useDeferredValue, useEffect, useRef, useState } from "react";
import type { PluginAction, PluginRenderResult, TreeNode, TreeWindowPayload } from "../../services/types";
import type { WebBotClient } from "../../services/webBotClient";
import { PluginActionBar } from "./PluginActionBar";

type Props = {
  botAlias: string;
  client: WebBotClient;
  view: Extract<PluginRenderResult, { renderer: "tree" }>;
  onRunAction?: (action: PluginAction, payload?: Record<string, unknown>) => void | Promise<void>;
};

function replaceChildren(nodes: TreeNode[], nodeId: string, children: TreeNode[]): TreeNode[] {
  return nodes.map((node) => {
    if (node.id === nodeId) {
      return {
        ...node,
        children,
      };
    }
    if (!node.children?.length) {
      return node;
    }
    return {
      ...node,
      children: replaceChildren(node.children, nodeId, children),
    };
  });
}

export function TreeView({ botAlias, client, view, onRunAction }: Props) {
  const session = view.mode === "session" ? view : null;
  const summary = view.mode === "session"
    ? view.summary
    : {
        roots: view.payload.roots,
        actions: view.payload.actions,
        searchable: true,
      };
  const initialRoots = view.mode === "session"
    ? view.initialWindow.roots || summary.roots || []
    : view.payload.roots;
  const [roots, setRoots] = useState<TreeNode[]>(initialRoots);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
  const requestIdRef = useRef(0);

  useEffect(() => {
    setRoots(initialRoots);
    setExpanded({});
    setQuery("");
  }, [initialRoots, view.sessionId]);

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
        kind: "search",
        query: deferredQuery,
      },
      controller.signal,
    ).then((payload) => {
      if (requestIdRef.current !== requestId) {
        return;
      }
      const next = payload as TreeWindowPayload;
      startTransition(() => {
        setRoots(next.roots || initialRoots);
      });
    }).catch((error) => {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      throw error;
    });
    return () => controller.abort();
  }, [botAlias, client, deferredQuery, initialRoots, session, view.pluginId, view.sessionId]);

  async function toggleNode(node: TreeNode) {
    const nextExpanded = !expanded[node.id];
    setExpanded((current) => ({ ...current, [node.id]: nextExpanded }));
    if (!nextExpanded || !session || !node.expandable || node.children?.length) {
      return;
    }
    const payload = await client.queryPluginViewWindow(botAlias, view.pluginId, view.sessionId, {
      kind: "children",
      nodeId: node.id,
    });
    const next = payload as TreeWindowPayload;
    setRoots((current) => replaceChildren(current, node.id, next.nodes || []));
  }

  function renderNodes(nodes: TreeNode[], depth = 0): JSX.Element[] {
    return nodes.flatMap((node) => {
      const isExpanded = !!expanded[node.id];
      const indent = depth * 16;
      const current = (
        <div key={node.id} className="border-b border-[var(--border)]/70 px-3 py-2 text-sm">
          <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2" style={{ paddingLeft: indent }}>
              <button
                type="button"
                onClick={() => void toggleNode(node)}
                className="h-6 w-6 rounded border border-[var(--border)] text-xs text-[var(--muted)]"
                disabled={!node.expandable}
                aria-label={isExpanded ? `折叠 ${node.label}` : `展开 ${node.label}`}
              >
                {node.expandable ? (isExpanded ? "−" : "+") : "·"}
              </button>
              <div className="min-w-0">
                <div className="truncate text-[var(--text)]">{node.label}</div>
                {node.description ? <div className="truncate text-xs text-[var(--muted)]">{node.description}</div> : null}
              </div>
              {node.badge ? (
                <span className="rounded-full bg-[var(--surface-strong)] px-2 py-0.5 text-xs text-[var(--muted)]">{node.badge}</span>
              ) : null}
            </div>
            <div className="flex items-center gap-2">
              {(node.actions || []).map((action) => (
                <button
                  key={`${node.id}-${action.id}`}
                  type="button"
                  disabled={action.disabled}
                  onClick={() => onRunAction?.(action, { nodeId: node.id })}
                  className="rounded-lg border border-[var(--border)] px-2 py-1 text-xs text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-60"
                >
                  {action.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      );
      if (!isExpanded || !node.children?.length) {
        return [current];
      }
      return [current, ...renderNodes(node.children, depth + 1)];
    });
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <PluginActionBar actions={summary.actions} onRunAction={(action) => onRunAction?.(action)} />
      <div className="border-b border-[var(--border)] px-3 py-2">
        {summary.searchable !== false ? (
          <label className="flex items-center gap-2 text-sm text-[var(--muted)]">
            搜索
            <input
              value={query}
              onChange={(event) => setQuery(event.currentTarget.value)}
              className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-1.5 text-sm text-[var(--text)]"
            />
          </label>
        ) : null}
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {roots.length > 0 ? renderNodes(roots) : (
          <div className="px-3 py-8 text-center text-sm text-[var(--muted)]">无结果</div>
        )}
      </div>
    </div>
  );
}
