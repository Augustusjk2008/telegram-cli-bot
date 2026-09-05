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
  it("passes snake_case costs through the shared mapper and accepts mapped camelCase data", () => {
    const mapped = mapChatMessageContextUsage({
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

    expect(mapped).toEqual({ contextLeftPercent: 72, estimatedCost });
    expect(mapChatMessageContextUsage(mapped)).toEqual(mapped);
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
    { scope: "session", label: "会话累计估算费用", currency: "USD", compact: true, contextLeftPercent: 72 },
    { scope: "turn", label: "本轮估算费用", currency: "CNY", compact: true, contextLeftPercent: undefined },
    { scope: "request", label: "最近一次调用估算费用", currency: "USD", compact: false, contextLeftPercent: undefined },
  ] as const)("shows $scope costs with small decimal amounts on click", ({ scope, label, currency, compact, contextLeftPercent }) => {
    render(<ChatContextUsageBadge compact={compact} contextUsage={{
      contextLeftPercent,
      estimatedCost: { ...estimatedCost, scope, currency },
    }} />);

    const badge = screen.getByRole("button");
    expect(badge).toHaveTextContent(contextLeftPercent === undefined ? "费用详情" : "ctx 72%");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    fireEvent.click(badge);

    const tooltip = screen.getByRole("tooltip");
    expect(tooltip).toHaveTextContent(`${label}：${currency} 0.000000014`);
    expect(tooltip).toHaveTextContent(`输入费用：${currency} 0.00000001`);
    expect(tooltip).toHaveTextContent(`缓存读费用：${currency} 0.000000002`);
    expect(tooltip).toHaveTextContent(`缓存写费用：${currency} 0`);
    expect(tooltip).toHaveTextContent(`输出费用：${currency} 0.000000002`);
    expect(tooltip).toHaveTextContent("计价模型：priced-model");
    if (contextLeftPercent !== undefined) {
      expect(tooltip).toHaveTextContent("context left: 72%");
    }
  });

  it("shows a valid zero estimate without context window data", () => {
    render(<ChatContextUsageBadge contextUsage={mapChatMessageContextUsage({ estimatedCost: {
      ...estimatedCost, total: 0, input: 0, cacheRead: 0, cacheWrite: 0, output: 0,
    } })} />);

    fireEvent.click(screen.getByRole("button", { name: /费用详情/ }));
    expect(screen.getByRole("tooltip")).toHaveTextContent("会话累计估算费用：USD 0");
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
    expect(screen.getByRole("tooltip")).not.toHaveTextContent(/费用|计价模型|USD/);
  });
});
