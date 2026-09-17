import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { ChatTranslationControl } from "../components/ChatTranslationControl";
import type { ChatMessage } from "../services/types";

test.each([
  ["timeout", "翻译请求超时"],
  ["translation_skipped", "翻译模型跳过了本次翻译"],
  ["translation_failed", "翻译模型报告翻译失败"],
  [undefined, "未提供具体原因"],
])("exposes the unavailable translation reason on a hoverable wrapper (%s)", (error, reason) => {
  const item: ChatMessage = {
    id: "message", role: "user", text: "原文", createdAt: "2026-09-17",
    translation: { status: "failed", target_language: "en", source_digest: "digest", error },
  };
  const onChange = vi.fn();
  render(<ChatTranslationControl item={item} onChange={onChange} />);
  const button = screen.getByRole("button", { name: `翻译未完成，显示原文：${reason}` });
  expect(button).toBeDisabled();
  expect(button).toHaveClass("disabled:pointer-events-none");
  expect(button.parentElement).toHaveAttribute("title", `翻译未完成，显示原文：${reason}`);
  fireEvent.click(button);
  expect(onChange).not.toHaveBeenCalled();
});
