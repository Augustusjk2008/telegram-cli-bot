import { expect, test } from "vitest";
import { normalizeWindowsPathInput } from "../utils/windowsPath";

test("normalizeWindowsPathInput collapses repeated separators for drive paths", () => {
  expect(normalizeWindowsPathInput("C:\\\\workspace\\\\team3")).toBe("C:\\workspace\\team3");
});

test("normalizeWindowsPathInput preserves the UNC prefix while normalizing inner separators", () => {
  expect(normalizeWindowsPathInput("\\\\server\\\\share\\\\project")).toBe("\\\\server\\share\\project");
});

test("normalizeWindowsPathInput leaves plain command names unchanged", () => {
  expect(normalizeWindowsPathInput("codex")).toBe("codex");
});
