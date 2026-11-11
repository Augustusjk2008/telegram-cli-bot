import { act, cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { afterEach, expect, test, vi } from "vitest";
import { FileEditorSurface } from "../components/FileEditorSurface";
import { FileEditorDocument, getFileEditorDocument, pruneFileEditorDocuments } from "../utils/fileEditorSession";

const releases: (() => void)[] = [];

afterEach(() => {
  cleanup();
  releases.splice(0).forEach((release) => release());
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function attach(document: FileEditorDocument, id: string, onChange = vi.fn(), readOnly = false) {
  const parent = window.document.createElement("div");
  window.document.body.appendChild(parent);
  const view = document.createView(parent, id, [EditorState.readOnly.of(readOnly)], onChange);
  releases.push(() => { document.releaseView(view); parent.remove(); });
  return view;
}

function undoKey(view: EditorView, redo = false) {
  fireEvent.keyDown(view.contentDOM, { key: redo ? "y" : "z", code: redo ? "KeyY" : "KeyZ", ctrlKey: true });
}

test("two views share edits and one undo/redo timeline while mapping independent selections", () => {
  const document = new FileEditorDocument("abc");
  const leftChange = vi.fn();
  const rightChange = vi.fn();
  const left = attach(document, "left", leftChange);
  const right = attach(document, "right", rightChange);
  left.dispatch({ selection: { anchor: 0 } });
  right.dispatch({ selection: { anchor: 2 } });

  left.dispatch({ changes: { from: 0, insert: "L" }, selection: { anchor: 1 }, userEvent: "input.type" });
  expect(right.state.doc.toString()).toBe("Labc");
  expect(right.state.selection.main.head).toBe(3);
  expect(left.state.selection.main.head).toBe(1);
  expect(rightChange).not.toHaveBeenCalled();

  right.dispatch({ changes: { from: 4, insert: "R" }, selection: { anchor: 5 }, userEvent: "input.type" });
  expect(left.state.doc.toString()).toBe("LabcR");
  expect(left.state.selection.main.head).toBe(1);
  expect(leftChange.mock.calls).toEqual([["Labc"]]);
  expect(rightChange.mock.calls).toEqual([["LabcR"]]);

  undoKey(left);
  expect(left.state.doc.toString()).toBe("Labc");
  expect(right.state.doc.toString()).toBe("Labc");
  expect(right.state.selection.main.head).toBe(4);
  undoKey(right);
  expect(left.state.doc.toString()).toBe("abc");
  expect(right.state.doc.toString()).toBe("abc");
  undoKey(left, true);
  undoKey(right, true);
  expect(left.state.doc.toString()).toBe("LabcR");
  expect(right.state.doc.toString()).toBe("LabcR");
  expect(leftChange).toHaveBeenCalledTimes(3);
  expect(rightChange).toHaveBeenCalledTimes(3);
});

test("tab switches retain document history and each view's mapped cursor and scroll", () => {
  const document = new FileEditorDocument("abcdef");
  const left = attach(document, "left");
  const right = attach(document, "right");
  left.dispatch({ selection: { anchor: 2 } });
  right.dispatch({ selection: { anchor: 5 } });
  left.scrollDOM.scrollTop = 80;
  left.scrollDOM.scrollLeft = 12;
  right.scrollDOM.scrollTop = 160;
  document.releaseView(left);
  right.dispatch({ changes: { from: 0, insert: "x" }, userEvent: "input.type" });
  document.releaseView(right);

  const reopenedLeft = attach(document, "left");
  const reopenedRight = attach(document, "right");
  expect(reopenedLeft.state.selection.main.head).toBe(3);
  expect(reopenedRight.state.selection.main.head).toBe(6);
  expect(reopenedLeft.scrollDOM.scrollTop).toBe(80);
  expect(reopenedLeft.scrollDOM.scrollLeft).toBe(12);
  expect(reopenedRight.scrollDOM.scrollTop).toBe(160);
  undoKey(reopenedLeft);
  expect(reopenedRight.state.doc.toString()).toBe("abcdef");
  expect(reopenedRight.state.selection.main.head).toBe(5);
});

test("stale renders and intermediate canonical echoes cannot overwrite newer typing", () => {
  const document = new FileEditorDocument("a");
  const onChange = vi.fn();
  const view = attach(document, "left", onChange);
  const staleRevision = document.revision;
  view.dispatch({ changes: { from: 1, insert: "b" } });
  view.dispatch({ changes: { from: 2, insert: "c" } });

  document.synchronize("old asynchronous load", staleRevision);
  document.synchronize("a", document.revision);
  document.synchronize("ab", document.revision);
  expect(view.state.doc.toString()).toBe("abc");
  document.synchronize("abc", document.revision);
  document.synchronize("disk reload", document.revision);
  expect(view.state.doc.toString()).toBe("disk reload");
  expect(onChange.mock.calls).toEqual([["ab"], ["abc"]]);
  undoKey(view);
  expect(onChange).toHaveBeenLastCalledWith("abc");
});

test("closed documents are pruned and workspace identities never share documents", () => {
  const session = {};
  const document = getFileEditorDocument(session, "a.ts", "a");
  const view = attach(document, "left");
  view.dispatch({ changes: { from: 1, insert: "b" } });
  expect(getFileEditorDocument(session, "a.ts", "a")).toBe(document);
  expect(getFileEditorDocument({}, "a.ts", "a").value).toBe("a");
  pruneFileEditorDocuments(session, ["a.ts"]);
  expect(getFileEditorDocument(session, "a.ts", "a")).toBe(document);
  pruneFileEditorDocuments(session, []);
  expect(getFileEditorDocument(session, "a.ts", "a")).not.toBe(document);
});

test("initial asynchronous file loading does not add an undo that erases the file", () => {
  const document = new FileEditorDocument("");
  const view = attach(document, "left");
  document.synchronize("loaded", document.revision);
  expect(document.undo(view)).toBe(false);
  view.dispatch({ changes: { from: 6, insert: "!" } });
  expect(document.undo(view)).toBe(true);
  expect(view.state.doc.toString()).toBe("loaded");
  expect(document.undo(view)).toBe(false);
});

test("browser history input uses the shared history and a read-only view cannot undo", () => {
  const document = new FileEditorDocument("a");
  const left = attach(document, "left");
  const right = attach(document, "right");
  const readOnly = attach(document, "readonly", vi.fn(), true);
  left.dispatch({ changes: { from: 1, insert: "b" } });
  undoKey(readOnly);
  expect(document.value).toBe("ab");
  right.contentDOM.dispatchEvent(new InputEvent("beforeinput", { inputType: "historyUndo", bubbles: true, cancelable: true }));
  expect(left.state.doc.toString()).toBe("a");
  left.contentDOM.dispatchEvent(new InputEvent("beforeinput", { inputType: "historyRedo", bubbles: true, cancelable: true }));
  expect(right.state.doc.toString()).toBe("ab");
});

test("only the active surface saves or handles navigation commands; standalone remains active by default", () => {
  const leftSave = vi.fn();
  const rightSave = vi.fn();
  const leftNavigate = vi.fn();
  const rightNavigate = vi.fn();
  const props = { path: "a.txt", value: "abc", canSave: true, onChange: vi.fn(), onClose: vi.fn() };
  const { rerender } = render(<>
    <FileEditorSurface {...props} active onSave={leftSave} onResolveCodeNavigation={leftNavigate} />
    <FileEditorSurface {...props} active={false} onSave={rightSave} onResolveCodeNavigation={rightNavigate} />
  </>);
  fireEvent.keyDown(window, { key: "s", ctrlKey: true });
  expect(leftSave).toHaveBeenCalledTimes(1);
  expect(rightSave).not.toHaveBeenCalled();
  const navigationCommand = { kind: "definition" as const, requestId: "next" };
  rerender(<>
    <FileEditorSurface {...props} active={false} onSave={leftSave} onResolveCodeNavigation={leftNavigate} navigationCommand={navigationCommand} />
    <FileEditorSurface {...props} active onSave={rightSave} onResolveCodeNavigation={rightNavigate} navigationCommand={navigationCommand} />
  </>);
  fireEvent.keyDown(window, { key: "s", metaKey: true });
  expect(leftSave).toHaveBeenCalledTimes(1);
  expect(rightSave).toHaveBeenCalledTimes(1);
  expect(leftNavigate).not.toHaveBeenCalled();
  expect(rightNavigate).toHaveBeenCalledTimes(1);
  rerender(<FileEditorSurface {...props} onSave={leftSave} />);
  fireEvent.keyDown(window, { key: "s", ctrlKey: true });
  expect(leftSave).toHaveBeenCalledTimes(2);
});

test("real CodeMirror surfaces mirror synchronously without inactive autofocus or stale prop rewrites", async () => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  // JSDOM has no layout; these tests exercise actual editor transactions and focus.
  vi.spyOn(window, "requestAnimationFrame").mockImplementation(() => 0);
  const sessionKey = {};
  const leftChange = vi.fn();
  const rightChange = vi.fn();
  const props = { sessionKey, path: "a.txt", value: "a", documentPaths: ["a.txt"], onSave: vi.fn(), onClose: vi.fn() };
  const { container, rerender } = render(<>
    <FileEditorSurface {...props} viewId="left" active onChange={leftChange} />
    <FileEditorSurface {...props} viewId="right" active={false} onChange={rightChange} />
  </>);
  await waitFor(() => expect(container.querySelectorAll(".cm-editor")).toHaveLength(2));
  const [left, right] = [...container.querySelectorAll<HTMLElement>(".cm-editor")].map((element) => EditorView.findFromDOM(element)!);
  expect(left.hasFocus).toBe(true);
  expect(right.hasFocus).toBe(false);
  act(() => {
    left.dispatch({ changes: { from: 1, insert: "b" } });
    right.dispatch({ changes: { from: 2, insert: "c" } });
  });
  rerender(<>
    <FileEditorSurface {...props} value="ab" viewId="left" active onChange={leftChange} />
    <FileEditorSurface {...props} value="ab" viewId="right" active={false} onChange={rightChange} />
  </>);
  expect(left.state.doc.toString()).toBe("abc");
  expect(right.state.doc.toString()).toBe("abc");
  expect(leftChange.mock.calls).toEqual([["ab"]]);
  expect(rightChange.mock.calls).toEqual([["abc"]]);
  act(() => undoKey(left));
  expect(right.state.doc.toString()).toBe("ab");
});
