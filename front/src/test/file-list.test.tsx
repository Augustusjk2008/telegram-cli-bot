import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { FileList } from "../components/FileList";

test("folder actions include rename", async () => {
  const user = userEvent.setup();
  const onRename = vi.fn();
  const folder = { name: "long-folder-name", isDir: true };

  render(
    <FileList
      files={[folder]}
      onDirClick={vi.fn()}
      onFileClick={vi.fn()}
      onRename={onRename}
    />,
  );

  await user.click(screen.getByRole("button", { name: "更多操作 long-folder-name" }));
  await user.click(screen.getByRole("menuitem", { name: "重命名 long-folder-name" }));

  expect(onRename).toHaveBeenCalledWith(folder);
});
