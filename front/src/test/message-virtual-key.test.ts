import { describe, expect, it } from "vitest";
import { resolveMessageVirtualKey } from "../chat/messageVirtualKey";
import type { ChatMessage } from "../services/types";

const rows: ChatMessage[] = [
  { id: "raw-1", role: "assistant", text: "one", createdAt: "2026-07-11T00:00:00Z", meta: { clientStateKey: "virtual-1" } },
  { id: "raw-2", role: "assistant", text: "two", createdAt: "2026-07-11T00:00:01Z" },
];

describe("resolveMessageVirtualKey", () => {
  it("maps a raw message id to its virtual key", () => {
    expect(resolveMessageVirtualKey(rows, "raw-1", "", (row) => row.meta?.clientStateKey || row.id)).toBe("virtual-1");
  });

  it("falls back to the raw id when no derived key exists", () => {
    expect(resolveMessageVirtualKey(rows, "raw-2", "", () => "")).toBe("raw-2");
  });
});
