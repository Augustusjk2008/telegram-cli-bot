import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ChatContextUsageBadge } from "../components/ChatContextUsageBadge";
import { buildDisplayContextUsage } from "../chat/displayContextUsage";
import type { ChatMessage, ChatMessageContextUsage, ChatMessageEstimatedCost } from "../services/types";
import { mapChatMessageContextUsage } from "../utils/contextUsage";

const estimatedCost: ChatMessageEstimatedCost = {
  model: "priced-model",
  currency: "USD",
  scope: "session",
  total: 0.000000014,
  input: 0.00000001,
  cacheRead: 0.000000002,
  cacheWrite: 0,
  output: 0.000000002,
};

function costMessage(id: string, total?: number, provider = "codex", conversationId = "conversation"): ChatMessage {
  return {
    id, turnId: id, conversationId, role: "assistant", text: id, createdAt: "2026-09-17T00:00:00Z",
    meta: { contextUsage: {
      provider, contextLeftPercent: 72,
      ...(total === undefined ? {} : { estimatedCost: { ...estimatedCost, total } }),
    } },
  };
}

describe("Codex display cost differences", () => {
  it("uses raw preceding totals after growth, equality and resets without mutating messages", () => {
    const totals = [10, 15, 19, 19, 3, 8, 0, 2];
    const messages = totals.map((total, index) => costMessage(String(index), total));
    messages.splice(1, 0, { ...costMessage("question"), role: "user" });
    const snapshot = structuredClone(messages);
    const displayed = buildDisplayContextUsage(messages);
    expect(totals.map((_, index) => displayed.get(String(index))?.estimatedCost?.total))
      .toEqual([10, 5, 4, 19, 3, 5, 0, 2]);
    expect(messages).toEqual(snapshot);
    expect(displayed.get("1")?.contextLeftPercent).toBe(72);
  });

  it("does not subtract across missing costs, providers, currencies or conversations", () => {
    const messages = [
      costMessage("first", 10), costMessage("missing"), costMessage("after-missing", 20),
      costMessage("claude", 25, "claude"), costMessage("after-claude", 30),
      costMessage("other-conversation", 40, "codex", "other"),
      costMessage("same-conversation", 35),
      costMessage("other-currency", 50),
    ];
    messages.at(-1)!.meta!.contextUsage!.estimatedCost!.currency = "CNY";
    const displayed = buildDisplayContextUsage(messages);
    expect(messages.map((message) => displayed.get(message.id)?.estimatedCost?.total))
      .toEqual([10, undefined, 20, 25, 30, 40, 5, 50]);
  });

  it("recomputes partial and final values from history, including a changed native session", () => {
    const previous = costMessage("previous", 10);
    const current = costMessage("current", 13);
    previous.meta!.contextUsage!.sessionId = "old-session";
    current.meta!.contextUsage!.sessionId = "new-session";
    current.meta!.contextUsage!.estimatedCost!.isPartial = true;
    current.state = "error";
    expect(buildDisplayContextUsage([current]).get("current")?.estimatedCost?.total).toBe(13);
    expect(buildDisplayContextUsage([previous, current]).get("current")?.estimatedCost)
      .toMatchObject({ total: 3, isPartial: true });
    current.meta!.contextUsage!.estimatedCost!.total = 16;
    expect(buildDisplayContextUsage([previous, current]).get("current")?.estimatedCost?.total).toBe(6);
  });
});

describe("context usage cost mapping", () => {
  it.each([
    { provider: "codex", scope: "session" },
    { provider: "claude", scope: "session" },
  ])("maps $provider costs without changing amounts and accepts mapped camelCase data", ({ provider, scope }) => {
    const mapped = mapChatMessageContextUsage({
      provider,
      context_left_percent: 72,
      estimated_cost: {
        model: estimatedCost.model,
        currency: estimatedCost.currency,
        scope: estimatedCost.scope,
        total: estimatedCost.total,
        input: estimatedCost.input,
        cache_read: estimatedCost.cacheRead,
        cache_write: estimatedCost.cacheWrite,
        output: estimatedCost.output,
      },
    });

    expect(mapped).toEqual({ provider, contextLeftPercent: 72, estimatedCost: { ...estimatedCost, scope } });
    expect(mapChatMessageContextUsage({ provider, contextLeftPercent: 72, estimatedCost })).toEqual(mapped);
    expect(mapChatMessageContextUsage(mapped)).toEqual(mapped);
    expect(estimatedCost.scope).toBe("session");
  });

  it("drops incomplete or invalid costs while preserving existing context details", () => {
    const invalidCosts: unknown[] = [undefined, null, {}, [],
      { ...estimatedCost, model: " " },
      { ...estimatedCost, currency: "" },
      { ...estimatedCost, scope: "unknown" },
    ];
    for (const field of ["total", "input", "cacheRead", "cacheWrite", "output"]) {
      for (const value of [undefined, null, NaN, Infinity, -1, "0"]) {
        invalidCosts.push({ ...estimatedCost, [field]: value });
      }
    }
    for (const cost of invalidCosts) {
      expect(mapChatMessageContextUsage({ estimatedCost: cost })).toBeUndefined();
      expect(mapChatMessageContextUsage({ context_left_percent: 72, estimatedCost: cost }))
        .toEqual({ contextLeftPercent: 72 });
    }
  });
});

describe("context usage cost details", () => {
  it("keeps unknown costs hidden even for unvalidated component data", () => {
    const { rerender } = render(<ChatContextUsageBadge contextUsage={{}} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();

    const contextUsage = { estimatedCost: { ...estimatedCost, output: undefined } } as ChatMessageContextUsage;
    rerender(<ChatContextUsageBadge contextUsage={contextUsage} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();

    rerender(<ChatContextUsageBadge contextUsage={{ ...contextUsage, contextLeftPercent: 72 }} />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("tooltip")).toHaveTextContent("context left: 72%");
    expect(screen.getByRole("tooltip")).not.toHaveTextContent(/cost|priced-model|USD/i);
  });

});
