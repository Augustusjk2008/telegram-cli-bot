import { describe, expect, it } from "vitest";
import { vi } from "vitest";
import {
  HISTORY_DELTA_MAX_PAGES,
  HistoryRevisionState,
  applyHistoryDelta,
  historyScopeKey,
} from "../chat/historyDeltaState";
import type { ChatMessage } from "../services/types";

const message = (id: string, text = id): ChatMessage => ({
  id,
  role: "assistant",
  text,
  createdAt: "2026-07-11T00:00:00Z",
  state: "done",
});

const mainScope = {
  botAlias: "main",
  agentId: "main",
  executionMode: "cli" as const,
  conversationId: "conversation-1",
};

describe("HistoryRevisionState", () => {
  it("upserts messages by id and applies tombstones", () => {
    const next = applyHistoryDelta([message("a"), message("b", "old")], {
      items: [message("b", "updated"), message("c")],
      deletedIds: ["a"],
      reset: false,
    });

    expect(next.map((item) => [item.id, item.text])).toEqual([
      ["b", "updated"],
      ["c", "c"],
    ]);
  });

  it("tracks revision and cursor independently for each chat scope", () => {
    const state = new HistoryRevisionState();
    const otherScope = { ...mainScope, conversationId: "conversation-2" };

    state.apply(mainScope, [message("a")], {
      items: [message("a", "updated")],
      revision: 7,
      nextCursor: "cursor-7",
      reset: false,
    });

    expect(state.query(mainScope, [message("a")])).toEqual({
      afterId: "a",
      revision: 7,
      cursor: "cursor-7",
    });
    expect(state.query(otherScope, [message("z")])).toEqual({
      afterId: "z",
      revision: 0,
      cursor: "",
    });
    expect(historyScopeKey(mainScope)).not.toBe(historyScopeKey(otherScope));
  });

  it("uses reset payloads as an authoritative snapshot", () => {
    expect(applyHistoryDelta([message("old")], {
      items: [message("fresh")],
      deletedIds: [],
      reset: true,
      reason: "cursor_expired",
    })).toEqual([message("fresh")]);
  });

  it("rejects an older revision and never resurrects a tombstoned message", () => {
    const state = new HistoryRevisionState();
    const removed = state.apply(mainScope, [message("a"), message("b")], {
      items: [],
      deletedIds: ["a"],
      revision: 8,
      reset: false,
    });

    const stale = state.apply(mainScope, removed.items, {
      items: [message("a", "stale"), message("b", "stale")],
      revision: 7,
      reset: false,
    });
    const newer = state.apply(mainScope, stale.items, {
      items: [message("a", "late resurrection"), message("b", "new")],
      revision: 9,
      reset: false,
    });

    expect(stale).toMatchObject({ stale: true, items: [message("b")] });
    expect(newer.items.map((item) => [item.id, item.text])).toEqual([["b", "new"]]);
    expect(state.query(mainScope, newer.items).revision).toBe(9);
  });

  it("shares one in-flight delta drain and exhausts every hasMore page", async () => {
    const state = new HistoryRevisionState();
    const fetchPage = vi.fn(async (query: { cursor: string }) => query.cursor
      ? { items: [message("b")], revision: 2, nextCursor: "", hasMore: false, reset: false }
      : { items: [message("a")], revision: 1, nextCursor: "page-2", hasMore: true, reset: false });

    const first = state.sync(mainScope, [], fetchPage);
    const second = state.sync(mainScope, [], fetchPage);
    const [left, right] = await Promise.all([first, second]);

    expect(first).toBe(second);
    expect(fetchPage).toHaveBeenCalledTimes(2);
    expect(left.items.map((item) => item.id)).toEqual(["a", "b"]);
    expect(right).toBe(left);
  });

  it("caps a malformed hasMore loop", async () => {
    const state = new HistoryRevisionState();
    const fetchPage = vi.fn(async () => ({
      items: [],
      revision: 1,
      nextCursor: "same-cursor",
      hasMore: true,
      reset: false,
    }));

    const result = await state.sync(mainScope, [], fetchPage);

    expect(fetchPage).toHaveBeenCalledTimes(HISTORY_DELTA_MAX_PAGES);
    expect(result).toMatchObject({ capped: true, hasMore: true });
  });

  it("does not commit any fetched revision when a paged sync becomes obsolete", async () => {
    const state = new HistoryRevisionState();
    let current = true;
    let fetchCount = 0;

    const result = await state.sync(
      mainScope,
      [message("assistant-1", "streaming")],
      async (query) => {
        fetchCount += 1;
        if (fetchCount === 1) {
          expect(query).toMatchObject({ revision: 0, cursor: "" });
          return {
            items: [message("assistant-1", "persisted preview")],
            revision: 4,
            nextCursor: "page-2",
            hasMore: true,
            reset: false,
          };
        }
        current = false;
        return {
          items: [message("assistant-1", "final answer")],
          revision: 5,
          nextCursor: "",
          hasMore: false,
          reset: false,
        };
      },
      { isCurrent: () => current },
    );

    expect(result.stale).toBe(true);
    expect(state.query(mainScope, [message("assistant-1")])).toMatchObject({
      revision: 0,
      cursor: "",
    });
  });
});
