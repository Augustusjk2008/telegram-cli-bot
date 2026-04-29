import { expect, test } from "vitest";
import { resolvePreviewFilePath } from "../utils/fileLinks";

test("normalizes slash-prefixed Windows absolute file links for preview", () => {
  expect(
    resolvePreviewFilePath("/C:/workspace/project/README.md", "C:/workspace/project"),
  ).toBe("README.md");
});

test("strips trailing line numbers from file links before preview", () => {
  expect(
    resolvePreviewFilePath("/C:/workspace/project/src/app.ts:12", "C:/workspace/project"),
  ).toBe("src/app.ts");

  expect(
    resolvePreviewFilePath("C:/logs/app.log:45:3", "C:/workspace/project"),
  ).toBe("C:/logs/app.log");
});
