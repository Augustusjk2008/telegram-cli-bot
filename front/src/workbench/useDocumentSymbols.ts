import { useEffect, useRef, useState } from "react";
import type { CodeDocumentSymbol, CodeIntelligenceResult, CodePosition } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { inferFileEditorLanguageId } from "../utils/fileEditorLanguage";
import type { EditorTab } from "./workbenchTypes";

const SYMBOL_REFRESH_DELAY_MS = 500;
const SHARED_RESULT_TTL_MS = 3000;

export type DocumentSymbolsStatus = "idle" | "loading" | "ready" | "unavailable";

export type DocumentSymbolsState = {
  status: DocumentSymbolsStatus;
  symbols: CodeDocumentSymbol[];
  /** Path the symbols belong to; a stale list must never be shown for another file. */
  path: string;
};

type SymbolDocument = Pick<EditorTab, "path" | "content" | "documentVersion" | "kind" | "sourceId" | "displayPath" | "loading">;

const IDLE: DocumentSymbolsState = { status: "idle", symbols: [], path: "" };

// The breadcrumb and the outline ask for the same document; one request serves both.
const sharedRequests = new WeakMap<WebBotClient, Map<string, Promise<CodeIntelligenceResult>>>();
let requestSequence = 0;

function requestSymbols(client: WebBotClient, botAlias: string, tab: SymbolDocument) {
  let requests = sharedRequests.get(client);
  if (!requests) {
    requests = new Map();
    sharedRequests.set(client, requests);
  }
  const version = Math.max(1, Math.trunc(tab.documentVersion || 1));
  const key = `${botAlias}\n${tab.path}\n${version}\n${tab.content.length}`;
  const pending = requests.get(key);
  if (pending) return pending;
  const request = client.queryCodeIntelligence(botAlias, {
    kind: "documentSymbols",
    requestId: `document-symbols-${Date.now()}-${++requestSequence}`,
    document: {
      ...(tab.kind === "external-source" && tab.sourceId ? { sourceId: tab.sourceId } : { path: tab.path }),
      languageId: inferFileEditorLanguageId(tab.displayPath || tab.path),
      version,
      content: tab.content,
    },
  });
  requests.set(key, request);
  const release = () => {
    window.setTimeout(() => {
      if (requests.get(key) === request) requests.delete(key);
    }, SHARED_RESULT_TTL_MS);
  };
  request.then(release, () => {
    if (requests.get(key) === request) requests.delete(key);
  });
  return request;
}

/** Symbols of the active document from the language server, refreshed after edits settle. */
export function useDocumentSymbols(
  client: WebBotClient,
  botAlias: string,
  tab: SymbolDocument | null,
  enabled: boolean,
  refreshKey: unknown = "",
): DocumentSymbolsState {
  const [state, setState] = useState<DocumentSymbolsState>(IDLE);
  const loadedPathRef = useRef("");
  const path = tab?.path || "";
  const usable = Boolean(
    enabled
    && tab
    && !tab.loading
    && (tab.kind === "file" || tab.kind === "external-source"),
  );
  const tabRef = useRef(tab);
  tabRef.current = tab;

  useEffect(() => {
    if (!usable || !path) {
      loadedPathRef.current = "";
      setState(enabled || !path ? IDLE : { status: "unavailable", symbols: [], path });
      return undefined;
    }
    let cancelled = false;
    // A newly shown file loads at once; edits wait until typing pauses.
    const firstLoad = loadedPathRef.current !== path;
    if (firstLoad) setState({ status: "loading", symbols: [], path });
    const timer = window.setTimeout(() => {
      const current = tabRef.current;
      if (!current || current.path !== path) return;
      requestSymbols(client, botAlias, current)
        .then((result) => {
          if (cancelled) return;
          loadedPathRef.current = path;
          if (!result.available || !result.supported) {
            setState({ status: "unavailable", symbols: [], path });
            return;
          }
          // While the server is still indexing an empty answer says nothing; keep what is shown.
          if (result.symbols.length === 0 && result.message) {
            setState((previous) => previous.path === path && previous.status === "ready"
              ? previous
              : { status: "ready", symbols: [], path });
            return;
          }
          setState({ status: "ready", symbols: result.symbols, path });
        })
        .catch(() => {
          if (!cancelled) setState({ status: "unavailable", symbols: [], path });
        });
    }, firstLoad ? 0 : SYMBOL_REFRESH_DELAY_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [botAlias, client, enabled, path, refreshKey, tab?.content, tab?.documentVersion, usable]);

  return state.path === path ? state : IDLE;
}

function containsPosition(symbol: CodeDocumentSymbol, position: CodePosition) {
  const { start, end } = symbol.range;
  if (position.line < start.line || position.line > end.line) return false;
  if (position.line === start.line && position.column < start.column) return false;
  if (position.line === end.line && position.column > end.column) return false;
  return true;
}

/** Symbols enclosing a position, outermost first. */
export function findDocumentSymbolPath(
  symbols: readonly CodeDocumentSymbol[],
  position: CodePosition | null,
): CodeDocumentSymbol[] {
  const path: CodeDocumentSymbol[] = [];
  if (!position) return path;
  let level = symbols;
  for (let depth = 0; depth < 32; depth += 1) {
    // Declarations do not overlap, but a later sibling wins if a server reports loose ranges.
    let match: CodeDocumentSymbol | null = null;
    for (const symbol of level) {
      if (containsPosition(symbol, position)) match = symbol;
    }
    if (!match) break;
    path.push(match);
    level = match.children;
  }
  return path;
}
