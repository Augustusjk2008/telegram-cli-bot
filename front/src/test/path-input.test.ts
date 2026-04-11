import { expect, test } from "vitest";
import { normalizePathInput } from "../utils/pathInput";

test("normalizePathInput trims Linux paths without rewriting separators", () => {
  expect(normalizePathInput("  /srv/telegram-cli-bridge/app  ")).toBe("/srv/telegram-cli-bridge/app");
});

test("normalizePathInput leaves plain command names unchanged", () => {
  expect(normalizePathInput("codex")).toBe("codex");
});
