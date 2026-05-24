import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { test, expect, vi } from "vitest";
import { AvatarPicker } from "../components/AvatarPicker";

const avatarAssets = [
  { name: "avatar_01.png", url: "/assets/avatars/avatar_01.png" },
  { name: "avatar_02.png", url: "/assets/avatars/avatar_02.png" },
  { name: "avatar_03.png", url: "/assets/avatars/avatar_03.png" },
];

test("opens the avatar dropdown and selects an avatar", async () => {
  const user = userEvent.setup();
  const handleSelect = vi.fn();

  render(
    <AvatarPicker
      assets={avatarAssets}
      selectedName="avatar_01.png"
      previewAlt="Bot 头像预览"
      selectLabel="Bot 头像"
      onSelect={handleSelect}
    />,
  );

  const trigger = screen.getByRole("button", { name: "Bot 头像" });
  await user.click(trigger);

  const optionButton = screen.getByRole("button", { name: "选择头像 avatar_02.png" });
  await user.click(optionButton);

  expect(handleSelect).toHaveBeenCalledWith("avatar_02.png");
  expect(screen.queryByRole("button", { name: "选择头像 avatar_02.png" })).not.toBeInTheDocument();
});
