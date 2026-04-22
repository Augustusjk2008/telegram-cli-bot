import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { BotListScreen } from "../screens/BotListScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { CreateBotInput, DirectoryListing } from "../services/types";

class DirectoryPickerClient extends MockWebBotClient {
  browserPath = "/workspace";
  addBotCalls: CreateBotInput[] = [];
  private readonly directoryMap: Record<string, DirectoryListing["entries"]> = {
    "/workspace": [
      { name: "repos", isDir: true },
      { name: "notes.txt", isDir: false, size: 12 },
    ],
    "/workspace/repos": [
      { name: "team-a", isDir: true },
      { name: "team-b", isDir: true },
    ],
    "/workspace/repos/team-a": [],
    "/workspace/repos/team-b": [],
  };

  async getCurrentPath(): Promise<string> {
    return "/workspace";
  }

  async listFiles(): Promise<DirectoryListing> {
    return {
      workingDir: this.browserPath,
      entries: this.directoryMap[this.browserPath] || [],
    };
  }

  async changeDirectory(_botAlias: string, path: string): Promise<string> {
    if (path === "..") {
      const parts = this.browserPath.split("/").filter(Boolean);
      parts.pop();
      this.browserPath = parts.length > 0 ? `/${parts.join("/")}` : "/";
      return this.browserPath;
    }
    this.browserPath = path.startsWith("/")
      ? path
      : this.browserPath === "/"
        ? `/${path}`
        : `${this.browserPath}/${path}`;
    return this.browserPath;
  }

  async addBot(input: CreateBotInput) {
    this.addBotCalls.push(input);
    return super.addBot(input);
  }
}

test("bot manager can browse and pick a workdir for a new bot", async () => {
  const user = userEvent.setup();
  const client = new DirectoryPickerClient();

  render(<BotListScreen client={client} onSelect={vi.fn()} />);

  expect(await screen.findByRole("heading", { name: "智能体管理" })).toBeInTheDocument();

  await user.type(screen.getByLabelText("新智能体别名"), "team3");
  await user.type(screen.getByLabelText("新智能体 CLI 路径"), "codex");
  await user.click(screen.getByRole("button", { name: "浏览新智能体工作目录" }));

  const dialog = await screen.findByRole("dialog", { name: "选择工作目录" });
  expect(within(dialog).getByText("/workspace")).toBeInTheDocument();

  await user.click(within(dialog).getByRole("button", { name: "进入目录 repos" }));
  await user.click(await within(dialog).findByRole("button", { name: "进入目录 team-a" }));

  expect(within(dialog).getByText("/workspace/repos/team-a")).toBeInTheDocument();

  await user.click(within(dialog).getByRole("button", { name: "使用当前目录" }));

  await waitFor(() => {
    expect(screen.queryByRole("dialog", { name: "选择工作目录" })).not.toBeInTheDocument();
  });

  expect(screen.getByLabelText("新智能体工作目录")).toHaveValue("/workspace/repos/team-a");
  expect(client.browserPath).toBe("/workspace");

  await user.click(screen.getByRole("button", { name: "创建智能体" }));

  await waitFor(() => {
    expect(client.addBotCalls).toHaveLength(1);
  });
  expect(client.addBotCalls[0]).toMatchObject({
    alias: "team3",
    cliPath: "codex",
    workingDir: "/workspace/repos/team-a",
  });
}, 10_000);
