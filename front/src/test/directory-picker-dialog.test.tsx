import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { DirectoryPickerDialog } from "../components/DirectoryPickerDialog";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { DirectoryListing } from "../services/types";

class DirectoryPickerClient extends MockWebBotClient {
  listPaths: Array<string | undefined> = [];

  async getCurrentPath(): Promise<string> {
    return "C:\\";
  }

  async listFiles(_botAlias: string, path?: string): Promise<DirectoryListing> {
    this.listPaths.push(path);
    const currentPath = path || "C:\\";
    if (currentPath === "::windows-drives::") {
      return {
        workingDir: "盘符列表",
        isVirtualRoot: true,
        entries: [
          { name: "C:\\", isDir: true },
          { name: "D:\\", isDir: true },
        ],
      };
    }
    return {
      workingDir: currentPath,
      entries: currentPath === "D:\\" ? [{ name: "repo", isDir: true }] : [],
    };
  }
}

test("directory picker navigates from windows drive root to drive list without mutating browse state", async () => {
  const user = userEvent.setup();
  const client = new DirectoryPickerClient();

  render(
    <DirectoryPickerDialog
      title="选择目录"
      botAlias="main"
      client={client}
      initialPath="C:\\"
      mutateBrowseState={false}
      onPick={vi.fn()}
      onClose={vi.fn()}
    />,
  );

  await screen.findByText("当前目录");
  await user.click(screen.getByRole("button", { name: "上一级" }));

  expect(await screen.findByText("盘符列表")).toBeInTheDocument();
  expect(client.listPaths).toContain("::windows-drives::");
  expect(screen.getByRole("button", { name: "使用当前目录" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "新增文件夹" })).toBeDisabled();

  await user.click(screen.getByRole("button", { name: "进入目录 D:\\" }));

  await waitFor(() => expect(client.listPaths).toContain("D:\\"));
  expect(await screen.findByText("D:\\")).toBeInTheDocument();
});
