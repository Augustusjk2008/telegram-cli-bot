import { EditorView } from "@codemirror/view";
import { undo, undoDepth } from "@codemirror/commands";
import { useState } from "react";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { FileEditorSurface } from "../components/FileEditorSurface";
import { applyResolvedAppearance, getCurrentAppearance } from "../theme/appearanceRuntime";

const initialAppearance = getCurrentAppearance();

afterEach(() => {
  cleanup();
  applyResolvedAppearance(initialAppearance);
  vi.unstubAllGlobals();
});

test("same-ID color and scheme changes preserve the editor, draft, selection and undo history", async () => {
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
  function appearance(scheme: "dark" | "light", revision: string, background: string) {
    return {
      ...initialAppearance, themeId: "theme_personal", scheme, revision,
      cssVariables: { ...initialAppearance.cssVariables, "--editor-bg": background },
    };
  }
  applyResolvedAppearance(appearance("dark", "editor-1", "#182028FF"));
  const original = "const unsavedDraft = true;";
  function DraftEditor() {
    const [value, setValue] = useState(original);
    return <FileEditorSurface path="draft.ts" value={value} dirty onChange={setValue} onSave={vi.fn()} onClose={vi.fn()} />;
  }
  const { container } = render(<DraftEditor />);
  const editor = await waitFor(() => {
    const element = container.querySelector<HTMLElement>(".cm-content");
    expect(element).not.toBeNull();
    const view = EditorView.findFromDOM(element!);
    expect(view).not.toBeNull();
    return view!;
  });
  act(() => editor.dispatch({ changes: { from: 0, insert: "// draft\n" }, selection: { anchor: 13, head: 17 } }));
  const draft = editor.state.doc.toString();
  const selection = editor.state.selection;
  expect(editor.state.facet(EditorView.darkTheme)).toBe(true);
  expect(undoDepth(editor.state)).toBe(1);

  for (const snapshot of [
    appearance("dark", "editor-2", "#25313DFF"),
    appearance("light", "editor-3", "#FFF8F0FF"),
    appearance("dark", "editor-4", "#151B22FF"),
  ]) {
    await act(async () => {
      applyResolvedAppearance(snapshot);
    });
    await waitFor(() => expect(editor.state.facet(EditorView.darkTheme)).toBe(snapshot.scheme === "dark"));
    expect(document.documentElement.style.getPropertyValue("--editor-bg")).toBe(snapshot.cssVariables["--editor-bg"]);
    expect(EditorView.findFromDOM(container.querySelector<HTMLElement>(".cm-content")!)).toBe(editor);
    expect(editor.state.doc.toString()).toBe(draft);
    expect(editor.state.selection.eq(selection)).toBe(true);
    expect(undoDepth(editor.state)).toBe(1);
  }
  act(() => { expect(undo(editor)).toBe(true); });
  expect(editor.state.doc.toString()).toBe(original);
});
