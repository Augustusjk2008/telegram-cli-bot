import { expect, test } from "vitest";
import { normalizePathInput } from "../utils/pathInput";

test("normalizePathInput trims Linux paths without rewriting separators", () => {
  expect(normalizePathInput("  /srv/telegram-cli-bridge/app  ")).toBe("/srv/telegram-cli-bridge/app");
});

test("normalizePathInput leaves plain command names unchanged", () => {
  expect(normalizePathInput("codex")).toBe("codex");
});

test("normalizePathInput collapses uniformly doubled Windows separators", () => {
  expect(normalizePathInput("  C:\\\\workspace\\\\picked  ")).toBe("C:\\workspace\\picked");
});

test("normalizePathInput preserves a real UNC path", () => {
  expect(normalizePathInput("\\\\server\\share\\workspace")).toBe("\\\\server\\share\\workspace");
});
