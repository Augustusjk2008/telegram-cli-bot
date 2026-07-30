import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ChatFinalAnswerActions } from "../components/ChatFinalAnswerActions";

describe("ChatFinalAnswerActions", () => {
  it("builds the full answer only when the copy action is used", async () => {
    const user = userEvent.setup();
    const buildFullAnswerText = vi.fn(() => "[过程]\n大段过程内容");

    render(<ChatFinalAnswerActions buildFullAnswerText={buildFullAnswerText} />);

    expect(buildFullAnswerText).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "复制完整回答" }));
    expect(buildFullAnswerText).toHaveBeenCalledTimes(1);
  });
});
