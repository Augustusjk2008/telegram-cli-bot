import { expect, test } from "vitest";
import { buildDisplayContextUsage } from "../chat/displayContextUsage";
import type { ChatMessage, ChatMessageEstimatedCost } from "../services/types";

function reply(id: string, cost?: Partial<ChatMessageEstimatedCost> & { total: number }): ChatMessage {
  return {
    id, turnId: id, conversationId: "c", role: "assistant", text: id, createdAt: "2026-11-17T00:00:00Z", state: "done",
    meta: { contextUsage: {
      provider: "codex",
      ...(cost ? { estimatedCost: { model: "gpt-6-astra", currency: "USD", scope: "turn", ...cost } } : {}),
    } },
  };
}

function shown(items: ChatMessage[]) {
  const display = buildDisplayContextUsage(items);
  return items.map((item) => {
    const total = display.get(item.id)?.estimatedCost?.total;
    return total === undefined ? null : Number(total.toFixed(4));
  });
}

test("a stopped Codex turn without a cost does not turn the next running total into a full-session amount", () => {
  expect(shown([reply("a", { total: 58.7381 }), reply("stopped"), reply("b", { total: 59.7894 })]))
    .toEqual([58.7381, null, 1.0513]);
});

test("per-turn amounts are shown as they are and taken out of the next running total", () => {
  expect(shown([
    reply("interrupted", { total: 26.2803, isPartial: true }),
    reply("running", { total: 39.1226 }),
    reply("own", { total: 1.05, basis: "turn" }),
    reply("own-2", { total: 0.5, basis: "turn" }),
  ])).toEqual([26.2803, 12.8423, 1.05, 0.5]);
});
