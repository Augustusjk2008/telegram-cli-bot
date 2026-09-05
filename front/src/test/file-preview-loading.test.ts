import { expect, test } from "vitest";
import type { FileReadResult } from "../services/types";
import { FILE_PREVIEW_FULL_READ_LIMIT_BYTES, shouldAutoLoadFullPreview } from "../utils/filePreview";

test.each(["config.json", "CONFIG.JSON", "index.html", "index.HTM", "index.xhtml"])(
  "%s only loads full content for an incomplete preview within the size limit",
  (path) => {
    const partial: FileReadResult = { content: "", mode: "head", fileSizeBytes: FILE_PREVIEW_FULL_READ_LIMIT_BYTES };
    expect(shouldAutoLoadFullPreview(path, partial)).toBe(true);
    expect(shouldAutoLoadFullPreview(path, { ...partial, isFullContent: true })).toBe(false);
    expect(shouldAutoLoadFullPreview(path, { ...partial, mode: "cat" })).toBe(false);
    expect(shouldAutoLoadFullPreview(path, { ...partial, fileSizeBytes: FILE_PREVIEW_FULL_READ_LIMIT_BYTES + 1 })).toBe(false);
    expect(shouldAutoLoadFullPreview(path, null)).toBe(false);
  },
);

test.each(["data.jsonc", "data.jsonl", "data.json.txt", "README.md"])("%s keeps ordinary partial previews", (path) => {
  expect(shouldAutoLoadFullPreview(path, { content: "", mode: "head", fileSizeBytes: 100 })).toBe(false);
});
