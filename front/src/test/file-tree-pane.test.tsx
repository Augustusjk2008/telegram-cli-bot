import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { DesktopWorkbench } from "../workbench/DesktopWorkbench";

function expectFileIcon(fileName: string, iconKind: string) {
  const button = screen.getByRole("button", { name: `打开 ${fileName}` });
  const iconKinds = Array.from(button.querySelectorAll("[data-icon]")).map((icon) => icon.getAttribute("data-icon"));
  expect(iconKinds).toContain(iconKind);
}

test("directory click expands the tree without changing the working directory", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockImplementation(async (_botAlias, path) => {
    if (!path || path === "/workspace") {
      return {
        workingDir: "/workspace",
        entries: [
          { name: "docs", isDir: true },
          { name: "README.md", isDir: false, size: 12 },
        ],
      };
    }
    if (path === "/workspace/docs") {
      return {
        workingDir: "/workspace/docs",
        entries: [
          { name: "project-plan.md", isDir: false, size: 24 },
        ],
      };
    }
    return {
      workingDir: path || "/workspace",
      entries: [],
    };
  });
  const changeDirectorySpy = vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      client={client}
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  await screen.findByText("README.md");
  const callsBeforeToggle = changeDirectorySpy.mock.calls.length;

  await user.click(screen.getByRole("button", { name: "展开 docs" }));

  await waitFor(() => {
    expect(screen.getByRole("button", { name: "打开 docs/project-plan.md" })).toBeInTheDocument();
  });
  expect(changeDirectorySpy).toHaveBeenCalledTimes(callsBeforeToggle);
});

test("desktop tree shows folder and file icons instead of arrow and dot markers", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockImplementation(async (_botAlias, path) => {
    if (!path || path === "/workspace") {
      return {
        workingDir: "/workspace",
        entries: [
          { name: "docs", isDir: true },
          { name: "README.md", isDir: false, size: 12 },
        ],
      };
    }
    return {
      workingDir: path || "/workspace",
      entries: [],
    };
  });

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      client={client}
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  const folderButton = await screen.findByRole("button", { name: "展开 docs" });
  const fileButton = screen.getByRole("button", { name: "打开 README.md" });

  expect(folderButton).not.toHaveTextContent("▸");
  expect(folderButton.querySelector('[data-icon="folder-closed"]')).not.toBeNull();
  expect(fileButton).not.toHaveTextContent("·");
  expect(fileButton.querySelector('[data-icon="file-markdown"]')).not.toBeNull();

  await user.click(folderButton);

  expect(await screen.findByRole("button", { name: "收起 docs" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "收起 docs" }).querySelector('[data-icon="folder-open"]')).not.toBeNull();
});

test("desktop tree maps common code and document families to dedicated icons", async () => {
  const client = new MockWebBotClient();
  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockResolvedValue({
    workingDir: "/workspace",
    entries: [
      { name: "main.cpp", isDir: false, size: 12 },
      { name: "app.py", isDir: false, size: 12 },
      { name: "index.ts", isDir: false, size: 12 },
      { name: "build.sh", isDir: false, size: 12 },
      { name: ".bashrc", isDir: false, size: 12 },
      { name: "Program.cs", isDir: false, size: 12 },
      { name: "Main.java", isDir: false, size: 12 },
      { name: "Dockerfile", isDir: false, size: 12 },
      { name: "CMakeLists.txt", isDir: false, size: 12 },
      { name: "README.md", isDir: false, size: 12 },
      { name: "notes.txt", isDir: false, size: 12 },
      { name: "report.pdf", isDir: false, size: 12 },
      { name: "data.csv", isDir: false, size: 12 },
      { name: "slides.pptx", isDir: false, size: 12 },
      { name: "logo.svg", isDir: false, size: 12 },
      { name: "song.mp3", isDir: false, size: 12 },
      { name: "movie.mp4", isDir: false, size: 12 },
      { name: "font.woff2", isDir: false, size: 12 },
      { name: "query.sql", isDir: false, size: 12 },
      { name: "archive.zip", isDir: false, size: 12 },
    ],
  });

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      client={client}
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  await screen.findByRole("button", { name: "打开 main.cpp" });

  expectFileIcon("main.cpp", "file-c-cpp");
  expectFileIcon("app.py", "file-python");
  expectFileIcon("index.ts", "file-js-ts");
  expectFileIcon("build.sh", "file-shell");
  expectFileIcon(".bashrc", "file-shell");
  expectFileIcon("Program.cs", "file-csharp");
  expectFileIcon("Main.java", "file-code");
  expectFileIcon("Dockerfile", "file-config");
  expectFileIcon("CMakeLists.txt", "file-config");
  expectFileIcon("README.md", "file-markdown");
  expectFileIcon("notes.txt", "file-text");
  expectFileIcon("report.pdf", "file-pdf");
  expectFileIcon("data.csv", "file-sheet");
  expectFileIcon("slides.pptx", "file-presentation");
  expectFileIcon("logo.svg", "file-image");
  expectFileIcon("song.mp3", "file-audio");
  expectFileIcon("movie.mp4", "file-video");
  expectFileIcon("font.woff2", "file-font");
  expectFileIcon("query.sql", "file-database");
  expectFileIcon("archive.zip", "file-archive");
});

test("tree can hand a directory off to embedded settings as the next workdir target", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockResolvedValue({
    workingDir: "/workspace",
    entries: [
      { name: "docs", isDir: true },
      { name: "README.md", isDir: false, size: 12 },
    ],
  });

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      client={client}
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  await screen.findByText("README.md");
  expect(screen.queryByRole("button", { name: "在终端中打开 docs" })).not.toBeInTheDocument();
  expect(screen.queryByText("设为 Bot 工作目录")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "设 docs 为 Bot 工作目录" }));

  expect(await screen.findByLabelText("工作目录")).toHaveValue("/workspace/docs");
});

test("desktop tree colors git states, bolds non-ignored text, and inherits child state on folders", async () => {
  localStorage.clear();
  const client = new MockWebBotClient();
  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockResolvedValue({
    workingDir: "/workspace",
    entries: [
      { name: "README.md", isDir: false, size: 12 },
      { name: "new.ts", isDir: false, size: 12 },
      { name: "package.json", isDir: false, size: 12 },
      { name: "src", isDir: true },
      { name: "docs", isDir: true },
      { name: "dist", isDir: true },
    ],
  });
  vi.spyOn(client, "getGitTreeStatus").mockResolvedValue({
    repoFound: true,
    workingDir: "/workspace",
    repoPath: "/workspace",
    items: {
      "README.md": "modified",
      "new.ts": "added",
      "src/app.ts": "modified",
      "src/nested/fresh.ts": "added",
      "docs/guide.md": "modified",
      dist: "ignored",
    },
  });

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      client={client}
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  const modifiedButton = await screen.findByRole("button", { name: "打开 README.md" });
  const addedButton = screen.getByRole("button", { name: "打开 new.ts" });
  const cleanButton = screen.getByRole("button", { name: "打开 package.json" });
  const inheritedAddedButton = screen.getByRole("button", { name: "展开 src" });
  const inheritedModifiedButton = screen.getByRole("button", { name: "展开 docs" });
  const ignoredButton = screen.getByRole("button", { name: "展开 dist" });
  const ignoredRow = ignoredButton.closest("[data-tree-path='dist']");

  await waitFor(() => {
    expect(modifiedButton).toHaveClass("text-yellow-400", "font-semibold");
    expect(addedButton).toHaveClass("text-emerald-500", "font-semibold");
    expect(cleanButton).toHaveClass("text-[var(--text)]", "font-semibold");
    expect(inheritedAddedButton).toHaveClass("text-emerald-500", "font-semibold");
    expect(inheritedModifiedButton).toHaveClass("text-yellow-400", "font-semibold");
  });
  expect(document.querySelector("[data-git-decoration]")).toBeNull();
  expect(ignoredRow).toHaveAttribute("data-git-ignored", "true");
  expect(ignoredButton).toHaveClass("text-[var(--muted)]");
  expect(ignoredButton).not.toHaveClass("font-semibold");
});
