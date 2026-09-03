import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ChatFinalAnswerActions } from "../components/ChatFinalAnswerActions";
import type { ChatMessageContextUsage } from "../services/types";

describe("ChatFinalAnswerActions", () => {
  it("builds the full answer only when the copy action is used", async () => {
    const user = userEvent.setup();
    const buildFullAnswerText = vi.fn(() => "[过程]\n大段过程内容");

    render(<ChatFinalAnswerActions buildFullAnswerText={buildFullAnswerText} />);

    expect(buildFullAnswerText).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "复制完整回答" }));
    expect(buildFullAnswerText).toHaveBeenCalledTimes(1);
  });

  it("opens context details when the usage badge is tapped", () => {
    const contextUsage: ChatMessageContextUsage = {
      contextLeftPercent: 72,
      contextWindow: 128_000,
      contextUsed: 35_840,
      inputTokens: 1_024,
      outputTokens: 512,
      model: "gpt-test",
    };

    render(<ChatFinalAnswerActions contextUsage={contextUsage} />);

    const badge = screen.getByTestId("chat-message-context-usage-bottom");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    fireEvent.pointerDown(badge, { pointerType: "touch" });
    fireEvent.pointerUp(badge, { pointerType: "touch" });
    fireEvent.click(badge);

    expect(screen.getByRole("tooltip")).toHaveTextContent("context left: 72%");
    expect(screen.getByRole("tooltip")).toHaveTextContent("context window: 128,000");
    expect(screen.getByRole("tooltip")).toHaveTextContent("model: gpt-test");

    fireEvent.pointerDown(document.body, { pointerType: "touch" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("keeps low context left text red and emphasized inside the interactive badge", () => {
    render(<ChatFinalAnswerActions contextUsage={{ contextLeftPercent: 20 }} />);

    const badge = screen.getByTestId("chat-message-context-usage-bottom");
    const text = screen.getByText("ctx 20%");

    expect(badge).toHaveClass("border-red-200", "bg-red-50");
    expect(text.tagName).toBe("SPAN");
    expect(text).toHaveClass("font-medium", "text-red-600");
  });

  it("supports focus, Escape, and a second tap for the context hint", () => {
    render(
      <ChatFinalAnswerActions
        contextUsage={{
          contextLeftPercent: 80,
          contextWindow: 64_000,
          contextUsed: 12_800,
        }}
      />,
    );

    const badge = screen.getByTestId("chat-message-context-usage-bottom");
    fireEvent.focus(badge);
    expect(screen.getByRole("tooltip")).toHaveTextContent("context left: 80%");

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    fireEvent.click(badge);
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    fireEvent.click(badge);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("keeps hover as a desktop entry point", () => {
    render(
      <ChatFinalAnswerActions
        contextUsage={{ contextLeftPercent: 61, contextWindow: 10_000, contextUsed: 3_900 }}
      />,
    );

    const badge = screen.getByTestId("chat-message-context-usage-bottom");
    fireEvent.pointerEnter(badge, { pointerType: "mouse" });
    expect(screen.getByRole("tooltip")).toHaveTextContent("context left: 61%");
    fireEvent.pointerLeave(badge, { pointerType: "mouse" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});
