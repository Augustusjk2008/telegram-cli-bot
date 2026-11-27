import { expect, test } from "vitest";
import { isExternalHref, isSafeMarkdownHref, isLikelyLocalFileHref, resolveMarkdownImagePath, resolvePreviewFilePath } from "../utils/fileLinks";

test("hrefs with a literal percent sign do not throw", () => {
  expect(isExternalHref("https://example.com/50%off")).toBe(true);
  expect(isSafeMarkdownHref("https://example.com/a%zz")).toBe(true);
  expect(resolvePreviewFilePath("docs/50%25%off.md", "")).toBe("docs/50%%off.md");
  expect(resolvePreviewFilePath("docs/%E4%B8%AD%zz.md", "")).toBe("docs/中%zz.md");
  expect(isSafeMarkdownHref("javascript%3Aalert(1)%zz")).toBe(false);
});

test("links keep encoded filename delimiters, POSIX case and the folder of an absolute Markdown file", () => {
  expect(isLikelyLocalFileHref("%23notes.md")).toBe(true);
  expect(resolvePreviewFilePath("file:///work/reports/a%23b%3Fc.md:12#section", "/work")).toBe("reports/a#b?c.md");
  expect(resolvePreviewFilePath("/other/Note.md", "/Other")).toBe("/other/Note.md");
  expect(resolveMarkdownImagePath("chart%231.png", "/tmp/reports/report.md")).toBe("/tmp/reports/chart#1.png");
});
