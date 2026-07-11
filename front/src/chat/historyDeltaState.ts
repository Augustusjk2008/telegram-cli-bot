import type { ChatExecutionMode, ChatMessage, HistoryDeltaResult } from "../services/types";

export type HistoryScope = {
  botAlias: string;
  agentId: string;
  executionMode: ChatExecutionMode;
  conversationId: string;
};

export type HistoryDeltaQueryState = {
  afterId: string;
  revision: number;
  cursor: string;
};

type ScopeState = {
  revision: number;
  cursor: string;
  revisionSupported: boolean;
  tombstones: Set<string>;
};

export const HISTORY_DELTA_MAX_PAGES = 20;

export type HistoryDeltaApplyResult = {
  items: ChatMessage[];
  revisionSupported: boolean;
  hasMore: boolean;
  reset: boolean;
  stale: boolean;
  capped?: boolean;
};

export function historyScopeKey(scope: HistoryScope) {
  return [scope.botAlias, scope.agentId || "main", scope.executionMode, scope.conversationId || "active"]
    .map((part) => encodeURIComponent(part))
    .join("/");
}

export function applyHistoryDelta(
  current: readonly ChatMessage[],
  delta: HistoryDeltaResult,
): ChatMessage[] {
  const deleted = new Set(delta.deletedIds || []);
  const next = (delta.reset ? [] : current).filter((item) => !deleted.has(item.id));
  const indexes = new Map(next.map((item, index) => [item.id, index]));

  for (const item of delta.items) {
    if (deleted.has(item.id)) {
      continue;
    }
    const index = indexes.get(item.id);
    if (typeof index === "number") {
      next[index] = item;
    } else {
      indexes.set(item.id, next.length);
      next.push(item);
    }
  }

  return next;
}

export class HistoryRevisionState {
  private readonly scopes = new Map<string, ScopeState>();
  private readonly inFlight = new Map<string, Promise<HistoryDeltaApplyResult>>();

  query(scope: HistoryScope, messages: readonly ChatMessage[]): HistoryDeltaQueryState {
    const state = this.scopes.get(historyScopeKey(scope));
    return {
      afterId: messages[messages.length - 1]?.id || "",
      revision: state?.revision ?? 0,
      cursor: state?.cursor || "",
    };
  }

  apply(scope: HistoryScope, messages: readonly ChatMessage[], delta: HistoryDeltaResult) {
    const key = historyScopeKey(scope);
    const previous = this.scopes.get(key);
    const revision = typeof delta.revision === "number" ? delta.revision : undefined;
    if (revision !== undefined && previous?.revisionSupported && revision < previous.revision) {
      return {
        items: [...messages],
        revisionSupported: true,
        hasMore: false,
        reset: false,
        stale: true,
      } satisfies HistoryDeltaApplyResult;
    }
    const revisionSupported = previous?.revisionSupported === true
      || revision !== undefined
      || Boolean(delta.nextCursor)
      || Boolean(delta.deletedIds?.length);
    const tombstones = delta.reset ? new Set<string>() : new Set(previous?.tombstones);
    for (const id of delta.deletedIds || []) {
      tombstones.add(id);
    }
    const filteredDelta = {
      ...delta,
      items: delta.items.filter((item) => !tombstones.has(item.id)),
    };
    this.scopes.set(key, {
      revision: revision ?? previous?.revision ?? 0,
      cursor: delta.nextCursor || "",
      revisionSupported,
      tombstones,
    });
    return {
      items: applyHistoryDelta(messages, filteredDelta),
      revisionSupported,
      hasMore: Boolean(delta.hasMore),
      reset: delta.reset,
      stale: false,
    } satisfies HistoryDeltaApplyResult;
  }

  sync(
    scope: HistoryScope,
    messages: readonly ChatMessage[],
    fetchPage: (query: HistoryDeltaQueryState) => Promise<HistoryDeltaResult>,
    maxPages = HISTORY_DELTA_MAX_PAGES,
  ): Promise<HistoryDeltaApplyResult> {
    const key = historyScopeKey(scope);
    const active = this.inFlight.get(key);
    if (active) {
      return active;
    }

    const task = (async () => {
      let current = [...messages];
      let result: HistoryDeltaApplyResult = {
        items: current,
        revisionSupported: this.scopes.get(key)?.revisionSupported === true,
        hasMore: false,
        reset: false,
        stale: false,
      };
      const pageLimit = Math.max(1, Math.floor(maxPages));
      for (let page = 0; page < pageLimit; page += 1) {
        const delta = await fetchPage(this.query(scope, current));
        result = this.apply(scope, current, delta);
        current = result.items;
        if (result.stale || !result.hasMore) {
          return result;
        }
      }
      return { ...result, capped: result.hasMore };
    })().finally(() => {
      this.inFlight.delete(key);
    });
    this.inFlight.set(key, task);
    return task;
  }

  clear(scope?: HistoryScope) {
    if (scope) {
      this.scopes.delete(historyScopeKey(scope));
      this.inFlight.delete(historyScopeKey(scope));
      return;
    }
    this.scopes.clear();
    this.inFlight.clear();
  }
}
