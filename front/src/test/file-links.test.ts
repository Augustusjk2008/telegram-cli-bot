import { expect, test } from "vitest";
import { buildFileDownloadUrl, resolveMarkdownImagePath, resolvePreviewFilePath } from "../utils/fileLinks";

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

test("resolves same-origin absolute file urls for preview", () => {
  expect(
    resolvePreviewFilePath("http://127.0.0.1:8765/abs/path/C:/workspace/project/docs/guide.md:1", "C:/workspace/project"),
  ).toBe("docs/guide.md");
});

test("resolves abs-path file urls for preview", () => {
  expect(
    resolvePreviewFilePath("/abs/path/C:/workspace/project/docs/guide.md:1", "C:/workspace/project"),
  ).toBe("docs/guide.md");
});
