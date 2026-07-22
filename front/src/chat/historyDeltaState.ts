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

export type HistoryDeltaSyncOptions = {
  maxPages?: number;
  isCurrent?: () => boolean;
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

function cloneScopeState(state: ScopeState | undefined): ScopeState | undefined {
  if (!state) {
    return undefined;
  }
  return {
    ...state,
    tombstones: new Set(state.tombstones),
  };
}

function queryForState(state: ScopeState | undefined, messages: readonly ChatMessage[]): HistoryDeltaQueryState {
  return {
    afterId: messages[messages.length - 1]?.id || "",
    revision: state?.revision ?? 0,
    cursor: state?.cursor || "",
  };
}

function applyDeltaToState(
  previous: ScopeState | undefined,
  messages: readonly ChatMessage[],
  delta: HistoryDeltaResult,
): { result: HistoryDeltaApplyResult; state: ScopeState | undefined } {
  const revision = typeof delta.revision === "number" ? delta.revision : undefined;
  if (revision !== undefined && previous?.revisionSupported && revision < previous.revision) {
    return {
      state: cloneScopeState(previous),
      result: {
        items: [...messages],
        revisionSupported: true,
        hasMore: false,
        reset: false,
        stale: true,
      },
    };
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
  return {
    state: {
      revision: revision ?? previous?.revision ?? 0,
      cursor: delta.nextCursor || "",
      revisionSupported,
      tombstones,
    },
    result: {
      items: applyHistoryDelta(messages, filteredDelta),
      revisionSupported,
      hasMore: Boolean(delta.hasMore),
      reset: delta.reset,
      stale: false,
    },
  };
}

export class HistoryRevisionState {
  private readonly scopes = new Map<string, ScopeState>();
  private readonly inFlight = new Map<string, Promise<HistoryDeltaApplyResult>>();
  private readonly scopeVersions = new Map<string, number>();
  private clearGeneration = 0;

  query(scope: HistoryScope, messages: readonly ChatMessage[]): HistoryDeltaQueryState {
    return queryForState(this.scopes.get(historyScopeKey(scope)), messages);
  }

  apply(scope: HistoryScope, messages: readonly ChatMessage[], delta: HistoryDeltaResult) {
    const key = historyScopeKey(scope);
    const previous = this.scopes.get(key);
    const applied = applyDeltaToState(previous, messages, delta);
    if (!applied.result.stale && applied.state) {
      this.scopes.set(key, applied.state);
      this.scopeVersions.set(key, (this.scopeVersions.get(key) ?? 0) + 1);
    }
    return applied.result;
  }

  sync(
    scope: HistoryScope,
    messages: readonly ChatMessage[],
    fetchPage: (query: HistoryDeltaQueryState) => Promise<HistoryDeltaResult>,
    options: HistoryDeltaSyncOptions = {},
  ): Promise<HistoryDeltaApplyResult> {
    const key = historyScopeKey(scope);
    const active = this.inFlight.get(key);
    if (active) {
      return active;
    }

    const startVersion = this.scopeVersions.get(key) ?? 0;
    const startClearGeneration = this.clearGeneration;
    const isCurrent = () => (
      this.clearGeneration === startClearGeneration
      && (this.scopeVersions.get(key) ?? 0) === startVersion
      && (options.isCurrent?.() ?? true)
    );
    const staleResult = (): HistoryDeltaApplyResult => ({
      items: [...messages],
      revisionSupported: this.scopes.get(key)?.revisionSupported === true,
      hasMore: false,
      reset: false,
      stale: true,
    });
    let task!: Promise<HistoryDeltaApplyResult>;
    task = (async () => {
      let current = [...messages];
      let candidateState = cloneScopeState(this.scopes.get(key));
      let result: HistoryDeltaApplyResult = {
        items: current,
        revisionSupported: candidateState?.revisionSupported === true,
        hasMore: false,
        reset: false,
        stale: false,
      };
      const pageLimit = Math.max(1, Math.floor(options.maxPages ?? HISTORY_DELTA_MAX_PAGES));
      for (let page = 0; page < pageLimit; page += 1) {
        const delta = await fetchPage(queryForState(candidateState, current));
        if (!isCurrent()) {
          return staleResult();
        }
        const applied = applyDeltaToState(candidateState, current, delta);
        result = applied.result;
        candidateState = applied.state;
        current = result.items;
        if (result.stale) {
          return result;
        }
        if (!result.hasMore) {
          if (!isCurrent()) {
            return staleResult();
          }
          if (candidateState) {
            this.scopes.set(key, candidateState);
            this.scopeVersions.set(key, startVersion + 1);
          }
          return result;
        }
      }
      if (!isCurrent()) {
        return staleResult();
      }
      if (candidateState) {
        this.scopes.set(key, candidateState);
        this.scopeVersions.set(key, startVersion + 1);
      }
      return { ...result, capped: result.hasMore };
    })().finally(() => {
      if (this.inFlight.get(key) === task) {
        this.inFlight.delete(key);
      }
    });
    this.inFlight.set(key, task);
    return task;
  }

  clear(scope?: HistoryScope) {
    if (scope) {
      const key = historyScopeKey(scope);
      this.scopes.delete(key);
      this.inFlight.delete(key);
      this.scopeVersions.set(key, (this.scopeVersions.get(key) ?? 0) + 1);
      return;
    }
    this.clearGeneration += 1;
    this.scopes.clear();
    this.inFlight.clear();
    this.scopeVersions.clear();
  }
}
