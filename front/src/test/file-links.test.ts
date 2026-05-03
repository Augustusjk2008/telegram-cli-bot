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

test("resolves markdown image paths relative to the markdown file", () => {
  expect(resolveMarkdownImagePath("assets/diagram.png", "docs/README.md")).toBe("docs/assets/diagram.png");
  expect(resolveMarkdownImagePath("../shared/logo.svg", "docs/guides/intro.md")).toBe("docs/guides/../shared/logo.svg");
  expect(resolveMarkdownImagePath("/assets/root.png", "docs/README.md")).toBe("assets/root.png");
  expect(resolveMarkdownImagePath("https://example.com/chart.png", "docs/README.md")).toBeNull();
});

test("builds same-origin file download urls for markdown images", () => {
  expect(buildFileDownloadUrl("main bot", "docs/assets/diagram.png")).toBe(
    "/api/bots/main%20bot/files/download?filename=docs%2Fassets%2Fdiagram.png",
  );
});
