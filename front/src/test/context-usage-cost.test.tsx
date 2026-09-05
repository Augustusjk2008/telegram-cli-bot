import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ChatContextUsageBadge } from "../components/ChatContextUsageBadge";
import type { ChatMessageContextUsage, ChatMessageEstimatedCost } from "../services/types";
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

describe("context usage cost mapping", () => {
  it.each([
    { provider: "codex", scope: "turn" },
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
  it.each([
    { scope: "session", currency: "USD", compact: true, contextLeftPercent: 72 },
    { scope: "turn", currency: "CNY", compact: true, contextLeftPercent: undefined },
    { scope: "request", currency: "USD", compact: false, contextLeftPercent: undefined },
  ] as const)("shows a single estimate for $scope with small decimal amounts on click", ({ scope, currency, compact, contextLeftPercent }) => {
    render(<ChatContextUsageBadge compact={compact} contextUsage={{
      contextLeftPercent,
      model: "gpt-test",
      estimatedCost: { ...estimatedCost, scope, currency },
    }} />);

    const badge = screen.getByRole("button");
    expect(badge).toHaveTextContent(contextLeftPercent === undefined ? "Estimated cost" : "ctx 72%");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    fireEvent.click(badge);

    const tooltip = screen.getByRole("tooltip");
    const costRows = tooltip.textContent!.split("\n").filter((row) => /cost/i.test(row));
    expect(costRows).toEqual([`Estimated cost: ${currency} 0.000000014`]);
    expect(tooltip).toHaveTextContent("model: gpt-test");
    expect(tooltip).not.toHaveTextContent(/pricing model|priced-model/i);
    if (contextLeftPercent !== undefined) {
      expect(tooltip).toHaveTextContent("context left: 72%");
    }
  });

  it("shows a valid zero estimate without context window data", () => {
    render(<ChatContextUsageBadge contextUsage={mapChatMessageContextUsage({ estimatedCost: {
      ...estimatedCost, total: 0, input: 0, cacheRead: 0, cacheWrite: 0, output: 0,
    } })} />);

    fireEvent.click(screen.getByRole("button", { name: /Estimated cost/ }));
    expect(screen.getByRole("tooltip")).toHaveTextContent("Estimated cost: USD 0");
  });

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
