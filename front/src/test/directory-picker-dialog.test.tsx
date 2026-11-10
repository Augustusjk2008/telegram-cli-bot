import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { DirectoryPickerDialog } from "../components/DirectoryPickerDialog";
import { MockWebBotClient } from "../services/mockWebBotClient";

const tree: Record<string, string[]> = {
  "/srv/work": ["alpha", "beta"],
  "/srv/work/alpha": [],
};

function renderPicker() {
  const client = new MockWebBotClient();
  const listFiles = vi.spyOn(client, "listFiles").mockImplementation(async (_alias, path) => {
    const dir = path || "/srv/work";
    return { workingDir: dir, entries: [...(tree[dir] ?? []).map((name) => ({ name, isDir: true })), { name: "README.md", isDir: false }] };
  });
  const mkdir = vi.spyOn(client, "createWorkdirDirectory").mockResolvedValue(undefined);
  const onPick = vi.fn();
  const onClose = vi.fn();
  render(
    <DirectoryPickerDialog
      title="选择工作目录"
      botAlias="main"
      client={client}
      mutateBrowseState={false}
      mode="workdir"
      onPick={onPick}
      onClose={onClose}
    />,
  );
  return { listFiles, mkdir, onPick, onClose, dialog: screen.getByRole("dialog", { name: "选择工作目录" }) };
}

test("browsing into a folder and using it picks that folder's path", async () => {
  const { listFiles, onPick, onClose, dialog } = renderPicker();
  expect(within(dialog).queryByRole("button", { name: "进入目录 README.md" })).not.toBeInTheDocument();
  fireEvent.click(await within(dialog).findByRole("button", { name: "进入目录 alpha" }));
  await waitFor(() => expect(listFiles).toHaveBeenLastCalledWith("main", "/srv/work/alpha"));
  expect(await within(dialog).findByText("当前目录没有子文件夹")).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "使用当前目录" }));
  await waitFor(() => expect(onPick).toHaveBeenCalledWith("/srv/work/alpha"));
  expect(onClose).toHaveBeenCalledTimes(1);
});

test("Enter creates a folder, except when it commits an IME composition", async () => {
  const { mkdir, dialog } = renderPicker();
  await within(dialog).findByRole("button", { name: "进入目录 alpha" });
  const input = within(dialog).getByLabelText("新文件夹名称");
  fireEvent.change(input, { target: { value: "wenjian" } });
  fireEvent.keyDown(input, { key: "Enter", keyCode: 229, isComposing: true });
  expect(mkdir).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { value: "文件" } });
  fireEvent.keyDown(input, { key: "Enter" });
  await waitFor(() => expect(mkdir).toHaveBeenCalledWith("main", "/srv/work", "文件"));
});

test("Escape closes the picker without picking", async () => {
  const { onPick, onClose, dialog } = renderPicker();
  await within(dialog).findByRole("button", { name: "进入目录 alpha" });
  fireEvent.keyDown(dialog, { key: "Escape" });
  await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  expect(onPick).not.toHaveBeenCalled();
});
