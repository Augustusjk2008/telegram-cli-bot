import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { UiThemeName } from "../theme";
import { FileTreePane } from "../workbench/FileTreePane";
import { useFileTree } from "../workbench/useFileTree";

function TreeHarness({ client, themeName, showPane = true }: { client: MockWebBotClient; themeName: UiThemeName; showPane?: boolean }) {
  const tree = useFileTree("main", client);
  if (!showPane) return null;
  return (
    <FileTreePane
      tree={tree}
      themeName={themeName}
      gitDecorations={{}}
      focused={false}
      onOpenFile={() => {}}
      onCreatedFile={() => {}}
      onRenamedFile={() => {}}
      onDeletedFile={() => {}}
      onRequestPreview={() => {}}
      onRequestUpload={async () => {}}
      onRequestHome={async () => {}}
      onRefreshGitDecorations={async () => {}}
      onRequestSetWorkdir={() => {}}
      onToggleFocus={() => {}}
    />
  );
}

beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(260);
});

afterEach(() => {
  vi.restoreAllMocks();
});

test("文件菜单按真实高度留在视口内，Esc 返回触发行", async () => {
  const client = new MockWebBotClient();
  vi.spyOn(client, "listFiles").mockResolvedValue({ workingDir: "C:\\workspace", entries: [{ name: "note.ts", isDir: false }] });
  const originalBounds = HTMLElement.prototype.getBoundingClientRect;
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    return this.getAttribute("role") === "menu"
      ? { x: 0, y: 0, left: 0, top: 0, right: 180, bottom: 300, width: 180, height: 300, toJSON: () => ({}) }
      : originalBounds.call(this);
  });
  render(<TreeHarness client={client} themeName="paper-daylight" />);
  const row = await screen.findByRole("button", { name: "打开 note.ts" });
  fireEvent.contextMenu(row, { clientX: window.innerWidth - 1, clientY: window.innerHeight - 1 });
  const menu = screen.getByRole("menu", { name: "文件树菜单" });
  expect(parseFloat(menu.style.left) + 180).toBeLessThanOrEqual(window.innerWidth - 8);
  expect(parseFloat(menu.style.top) + 300).toBeLessThanOrEqual(window.innerHeight - 8);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("menu", { name: "文件树菜单" })).not.toBeInTheDocument();
  expect(row).toHaveFocus();
});

test("自定义主题保持纸感行高、虚拟偏移、选中项和滚动位置", async () => {
  const client = new MockWebBotClient();
  vi.spyOn(client, "listFiles").mockResolvedValue({
    workingDir: "C:/workspace",
    entries: Array.from({ length: 1000 }, (_, index) => ({ name: `file-${String(index).padStart(4, "0")}.ts`, isDir: false })),
  });
  const { rerender } = render(<TreeHarness client={client} themeName="theme_custom_dark" />);
  let viewport = await screen.findByTestId("desktop-file-tree-virtual-list");
  expect(viewport.firstElementChild).toHaveStyle({ height: "26000px" });
  expect(viewport.querySelectorAll(".file-tree-row").length).toBeLessThan(50);
  viewport.scrollTop = 200 * 26;
  fireEvent.scroll(viewport);
  fireEvent.click(await screen.findByRole("button", { name: "打开 file-0205.ts" }));

  for (const themeName of ["paper-daylight", "theme_custom_light", "theme_custom_dark"]) {
    const before = viewport;
    rerender(<TreeHarness client={client} themeName={themeName} />);
    viewport = screen.getByTestId("desktop-file-tree-virtual-list");
    expect(viewport).toBe(before);
    const selected = screen.getByRole("button", { name: "打开 file-0205.ts" });
    expect(selected).toHaveAttribute("aria-current", "true");
    expect(selected.closest(".file-tree-row")).toHaveStyle({ height: "26px" });
    expect(selected.closest(".file-tree-row")?.parentElement).toHaveStyle({ height: "26px", top: `${205 * 26}px` });
    expect(viewport.scrollTop).toBe(200 * 26);
  }

  rerender(<TreeHarness client={client} themeName="theme_custom_dark" showPane={false} />);
  rerender(<TreeHarness client={client} themeName="theme_custom_light" />);
  viewport = screen.getByTestId("desktop-file-tree-virtual-list");
  expect(await screen.findByRole("button", { name: "打开 file-0205.ts" })).toHaveAttribute("aria-current", "true");
  expect(viewport.scrollTop).toBe(206 * 26 - 260);

  fireEvent.click(screen.getByTestId("desktop-file-tree-scroll"));
  viewport.scrollTop = 990 * 26;
  fireEvent.scroll(viewport);
  await screen.findByRole("button", { name: "打开 file-0999.ts" });
  rerender(<TreeHarness client={client} themeName="paper-daylight" />);
  expect(viewport.scrollTop).toBe(990 * 26);
  expect(await screen.findByRole("button", { name: "打开 file-0999.ts" })).not.toHaveAttribute("aria-current");
});
