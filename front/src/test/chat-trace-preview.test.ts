import { expect, test } from "vitest";
import { resolveChatTracePreviewConfig } from "../utils/chatTracePreview";

test("chat trace preview uses default limits when env is missing", () => {
  expect(resolveChatTracePreviewConfig({})).toEqual({
    maxLines: 5,
    maxChars: 200,
  });
});

test("chat trace preview accepts positive integer env overrides and ignores invalid values", () => {
  expect(resolveChatTracePreviewConfig({
    VITE_CHAT_TRACE_PREVIEW_MAX_LINES: "8",
    VITE_CHAT_TRACE_PREVIEW_MAX_CHARS: "320",
  })).toEqual({
    maxLines: 8,
    maxChars: 320,
  });

  expect(resolveChatTracePreviewConfig({
    VITE_CHAT_TRACE_PREVIEW_MAX_LINES: "0",
    VITE_CHAT_TRACE_PREVIEW_MAX_CHARS: "abc",
  })).toEqual({
    maxLines: 5,
    maxChars: 200,
  });
});
