import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { test, expect, vi } from "vitest";
import { AvatarPicker } from "../components/AvatarPicker";

const avatarAssets = [
  { name: "bot-default.png", url: "/assets/avatars/bot-default.png" },
  { name: "claude-blue.png", url: "/assets/avatars/claude-blue.png" },
  { name: "codex-slate.png", url: "/assets/avatars/codex-slate.png" },
];

test("keeps the avatar dropdown inside the viewport when the trigger is near the left edge", async () => {
  const user = userEvent.setup();
  const originalInnerWidth = window.innerWidth;

  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    value: 360,
    writable: true,
  });

  render(
    <AvatarPicker
      assets={avatarAssets}
      selectedName="bot-default.png"
      previewAlt="Bot 头像预览"
      selectLabel="Bot 头像"
      onSelect={() => undefined}
    />,
  );

  const trigger = screen.getByRole("button", { name: "Bot 头像" });
  const root = trigger.parentElement as HTMLDivElement;
  vi.spyOn(root, "getBoundingClientRect").mockReturnValue({
    x: 16,
    y: 24,
    width: 44,
    height: 44,
    top: 24,
    right: 60,
    bottom: 68,
    left: 16,
    toJSON: () => ({}),
  });

  await user.click(trigger);

  const optionButton = screen.getByRole("button", { name: "选择头像 claude-blue.png" });
  const panel = optionButton.parentElement?.parentElement as HTMLDivElement;

  expect(panel.style.left).toBe("0px");
  expect(panel.style.width).toBe("256px");

  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    value: originalInnerWidth,
    writable: true,
  });
});
