import { Terminal, type ILink } from "@xterm/xterm";
import { expect, test, vi } from "vitest";
import { workspaceRelativePath } from "../services/workspacePath";
import { terminalSourceLinkProvider } from "../terminal/terminalSourceLinks";

test("resolves against the launch directory and enforces the target workspace boundary", () => {
  const windows = (path: string) => workspaceRelativePath(path, "C:\\Repo\\build", "/C:/Repo/", true);
  expect(windows("..\\src\\App.ts")).toBe("src/App.ts");
  expect(windows("c:/repo/app.ts")).toBe("app.ts");
  expect(windows("D:/Repo/app.ts")).toBeNull();
  expect(windows("C:/Repo-other/app.ts")).toBeNull();
  expect(windows("..\\..\\private.ts")).toBeNull();
  expect(windows("C:relative.ts")).toBeNull();
  expect(workspaceRelativePath("../source", "/srv/Repo/build", "/srv/Repo", false)).toBe("source");
  expect(workspaceRelativePath("/srv/repo/source", "/srv/Repo", "/srv/Repo", false)).toBeNull();
  expect(workspaceRelativePath("a\\b.ts", "/srv", "/srv", false)).toBe("a\\b.ts");
});

test("links a quoted, soft-wrapped location by terminal cells and preserves plain selection and web links", async () => {
  const term = new Terminal({ cols: 12, rows: 12 });
  const open = vi.fn();
  try {
    await new Promise<void>((done) => term.write('错误 "src/a b.ts":42:7\r\nREADME:9\r\nhttps://host/app.ts:5', done));
    const provider = terminalSourceLinkProvider(term, "C:/repo", { root: "C:/repo", windows: true }, open);
    function links(y: number) {
      let result: ILink[] = [];
      provider.provideLinks(y, (found) => { result = found || []; });
      return result;
    }
    const link = links(2)[0];
    expect(link.range).toEqual({ start: { x: 6, y: 1 }, end: { x: 10, y: 2 } });
    const click = (ctrlKey: boolean, button: number) => link.activate(new MouseEvent("mouseup", { ctrlKey, button }), link.text);
    click(false, 0);
    click(true, 2);
    expect(open).not.toHaveBeenCalled();
    click(true, 0);
    expect(open).toHaveBeenCalledExactlyOnceWith({ path: "src/a b.ts", line: 42, column: 7 });
    const withoutColumn = links(3)[0];
    withoutColumn.activate(new MouseEvent("mouseup", { ctrlKey: true }), withoutColumn.text);
    expect(open).toHaveBeenLastCalledWith({ path: "README", line: 9, column: 1 });
    expect(links(4)).toEqual([]);
  } finally {
    term.dispose();
  }
});
