import { expect, test } from "vitest";
import { isExternalHref, isSafeMarkdownHref, resolvePreviewFilePath } from "../utils/fileLinks";

test("hrefs with a literal percent sign do not throw", () => {
  expect(isExternalHref("https://example.com/50%off")).toBe(true);
  expect(isSafeMarkdownHref("https://example.com/a%zz")).toBe(true);
  expect(resolvePreviewFilePath("docs/50%25%off.md", "")).toBe("docs/50%%off.md");
  expect(resolvePreviewFilePath("docs/%E4%B8%AD%zz.md", "")).toBe("docs/中%zz.md");
  expect(isSafeMarkdownHref("javascript%3Aalert(1)%zz")).toBe(false);
});
