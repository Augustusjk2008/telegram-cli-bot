import { describe, expect, test } from "vitest";

import { loadFileEditorExtensions } from "../utils/fileEditorLanguage";

describe("loadFileEditorExtensions", () => {
  test("loads CodeMirror extensions for C and C++ files", async () => {
    await expect(loadFileEditorExtensions("main.cpp")).resolves.toHaveLength(1);
    await expect(loadFileEditorExtensions("types.hpp")).resolves.toHaveLength(1);
    await expect(loadFileEditorExtensions("legacy.c")).resolves.toHaveLength(1);
  });

  test("returns no extensions for unknown file types", async () => {
    await expect(loadFileEditorExtensions("notes.txt")).resolves.toHaveLength(0);
  });
});
