import { describe, expect, it } from "vitest";
import { WeightedLruCache } from "../utils/lruCache";

describe("WeightedLruCache", () => {
  it("evicts the least recently used entry by entry count", () => {
    const cache = new WeightedLruCache<string, string>({ maxEntries: 2, maxWeight: 20, weigh: (value) => value.length });
    cache.set("a", "a");
    cache.set("b", "b");
    expect(cache.get("a")).toBe("a");
    cache.set("c", "c");
    expect(cache.get("b")).toBeUndefined();
    expect(cache.get("a")).toBe("a");
    expect(cache.get("c")).toBe("c");
  });

  it("enforces the total weight budget", () => {
    const cache = new WeightedLruCache<string, string>({ maxEntries: 10, maxWeight: 3, weigh: (value) => value.length });
    cache.set("a", "aa");
    cache.set("b", "bb");
    expect(cache.size).toBe(1);
    expect(cache.weight).toBe(2);
    expect(cache.get("a")).toBeUndefined();
    expect(cache.get("b")).toBe("bb");
  });
});
