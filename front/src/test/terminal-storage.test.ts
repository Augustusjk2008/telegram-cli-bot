import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { readTerminalOwnerId } from "../terminal/terminalStorage";

const STORAGE_KEY = "web-terminal-owner-id";

describe("readTerminalOwnerId", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  test.each(["", "   ", "null", "undefined"])("replaces invalid stored value %p", (storedValue) => {
    vi.stubGlobal("crypto", { randomUUID: vi.fn(() => "generated-owner") });
    localStorage.setItem(STORAGE_KEY, storedValue);

    expect(readTerminalOwnerId()).toBe("generated-owner");
    expect(localStorage.getItem(STORAGE_KEY)).toBe("generated-owner");
  });

  test("reuses valid stored value", () => {
    localStorage.setItem(STORAGE_KEY, "owner-1");

    expect(readTerminalOwnerId()).toBe("owner-1");
  });
});
