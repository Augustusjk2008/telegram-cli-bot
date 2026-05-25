import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ChatMessageMeta } from "../components/ChatMessageMeta";
import { resolveChatTracePreviewConfig } from "../utils/chatTracePreview";
import { extractPlanDraft, stripPlanDraftTags } from "../utils/planDraft";

afterEach(() => {
  vi.useRealTimers();
});

test("shows time only for messages from today", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-05-08T15:30:00+08:00"));

  render(<ChatMessageMeta name="助手" createdAt="2026-05-08T09:05:00+08:00" />);

  expect(screen.getByText("09:05")).toBeInTheDocument();
  expect(screen.queryByText(/\d{4}\/\d{2}\/\d{2}/)).not.toBeInTheDocument();
});

test("shows date and time for messages from another day", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-05-08T15:30:00+08:00"));
  const createdAt = "2026-05-07T09:05:00+08:00";
  const createdDate = new Date(createdAt);
  const expectedDate = createdDate.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const expectedTime = createdDate.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });

  render(<ChatMessageMeta name="助手" createdAt={createdAt} />);

  expect(screen.getByText(`${expectedDate} ${expectedTime}`)).toBeInTheDocument();
});

test("shows assistant context usage after time", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-05-08T15:30:00+08:00"));

  render(<ChatMessageMeta
    name="助手"
    createdAt="2026-05-08T09:05:00+08:00"
    contextUsage={{
      provider: "codex",
      source: "codex_session_token_count",
      sessionId: "thread-1",
      usedTokens: 76593,
      contextWindow: 258400,
      contextLeftPercent: 74,
      usedDisplay: "76.6K",
      windowDisplay: "258K",
      statusText: "74% context left · 76.6K / 258K",
    }}
  />);

  expect(screen.getByText("74% context left · 76.6K / 258K")).toBeInTheDocument();
  expect(screen.getByTitle("76.6K used / 258K window")).toBeInTheDocument();
});

test("chat trace preview resolves defaults and valid env overrides", () => {
  expect(resolveChatTracePreviewConfig({})).toEqual({
    maxLines: 5,
    maxChars: 200,
  });

  expect(resolveChatTracePreviewConfig({
    VITE_CHAT_TRACE_PREVIEW_MAX_LINES: "8",
    VITE_CHAT_TRACE_PREVIEW_MAX_CHARS: "320",
  })).toEqual({
    maxLines: 8,
    maxChars: 320,
  });
});

test("chat trace preview ignores invalid env overrides", () => {
  expect(resolveChatTracePreviewConfig({
    VITE_CHAT_TRACE_PREVIEW_MAX_LINES: "0",
    VITE_CHAT_TRACE_PREVIEW_MAX_CHARS: "abc",
  })).toEqual({
    maxLines: 5,
    maxChars: 200,
  });
});

test("plan draft helpers extract complete drafts and strip wrappers", () => {
  expect(extractPlanDraft("分析\n<PLAN_DRAFT>\n# 方案\n- A\n</PLAN_DRAFT>")).toBe("# 方案\n- A");
  expect(stripPlanDraftTags("前文\n<PLAN_DRAFT>\n# 方案\n</PLAN_DRAFT>\n后文")).toBe("# 方案");
});

test("plan draft extraction ignores incomplete draft", () => {
  expect(extractPlanDraft("<PLAN_DRAFT>\n# 方案")).toBe("");
});
