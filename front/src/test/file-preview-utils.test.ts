import { expect, test } from "vitest";
import type { FileReadResult } from "../services/types";
import {
  isHtmlPreviewPath,
  shouldAutoLoadFullHtmlPreview,
  withDetectedPreviewKind,
} from "../utils/filePreview";

test("detects html preview paths", () => {
  expect(isHtmlPreviewPath("index.html")).toBe(true);
  expect(isHtmlPreviewPath("report.HTM")).toBe(true);
  expect(isHtmlPreviewPath("README.md")).toBe(false);
});

test("marks fully loaded html as html preview", () => {
  const result: FileReadResult = {
    content: "<!doctype html><html><body>ok</body></html>",
    mode: "cat",
    fileSizeBytes: 64,
    isFullContent: true,
  };

  expect(withDetectedPreviewKind("index.html", result).previewKind).toBe("html");
});

test("does not mark partial html as html preview", () => {
  const result: FileReadResult = {
    content: "<html>",
    mode: "head",
    fileSizeBytes: 128,
    isFullContent: false,
  };

  expect(withDetectedPreviewKind("index.html", result).previewKind).toBeUndefined();
});

test("auto-loads html when preview is partial and under size limit", () => {
  const result: FileReadResult = {
    content: "<html>",
    mode: "head",
    fileSizeBytes: 128,
    isFullContent: false,
  };

  expect(shouldAutoLoadFullHtmlPreview("index.html", result)).toBe(true);
  expect(shouldAutoLoadFullHtmlPreview("README.md", result)).toBe(false);
});
