import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { FileTreePane } from "../workbench/FileTreePane";
import type { UseFileTreeResult } from "../workbench/useFileTree";

test("folder context menu includes rename", () => {
  const folder = { path: "docs", name: "docs", isDir: true };
  const tree = {
    rootPath: "C:/workspace",
    loading: false,
    error: "",
    rootEntries: [folder],
    branches: {},
    expandedPaths: [],
    highlightedPath: "",
    selectedPath: "",
    downloadProgress: null,
    selectPath: vi.fn(),
    clearSelection: vi.fn(),
    isExpanded: vi.fn(() => false),
    toggleDirectory: vi.fn().mockResolvedValue(undefined),
    refreshRoot: vi.fn().mockResolvedValue(undefined),
    refreshTreeAndRoot: vi.fn().mockResolvedValue("C:/workspace"),
    restoreExpandedPaths: vi.fn().mockResolvedValue(undefined),
    revealPath: vi.fn().mockResolvedValue(undefined),
    highlightPath: vi.fn(),
    createDirectory: vi.fn().mockResolvedValue(undefined),
    createFile: vi.fn(),
    renameFile: vi.fn(),
    copyFile: vi.fn(),
    moveFile: vi.fn(),
    deletePath: vi.fn(),
    downloadFile: vi.fn(),
    cancelDownload: vi.fn(),
  } satisfies UseFileTreeResult;

  render(
    <FileTreePane
      tree={tree}
      onOpenFile={vi.fn()}
      onCreatedFile={vi.fn()}
      onRenamedFile={vi.fn()}
      onDeletedFile={vi.fn()}
      onRequestPreview={vi.fn()}
      onRequestUpload={vi.fn().mockResolvedValue(undefined)}
      onRequestHome={vi.fn().mockResolvedValue(undefined)}
      gitDecorations={{}}
      onRefreshGitDecorations={vi.fn().mockResolvedValue(undefined)}
      onRequestSetWorkdir={vi.fn()}
      focused={false}
      onToggleFocus={vi.fn()}
    />,
  );

  fireEvent.contextMenu(screen.getByRole("button", { name: "展开 docs" }));

  const menu = screen.getByRole("menu", { name: "文件树菜单" });
  expect(within(menu).getByRole("button", { name: "改名" })).toBeInTheDocument();
});
