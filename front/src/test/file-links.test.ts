import { expect, test } from "vitest";
import { resolvePreviewFilePath } from "../utils/fileLinks";

test("normalizes slash-prefixed Windows absolute file links for preview", () => {
  expect(
    resolvePreviewFilePath("/C:/workspace/project/README.md", "C:/workspace/project"),
  ).toBe("README.md");
});
