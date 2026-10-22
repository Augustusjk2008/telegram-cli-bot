import { EditorView } from "@codemirror/view";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { FileEditorSurface } from "../components/FileEditorSurface";

afterEach(() => {
  cleanup();
  delete document.documentElement.dataset.theme;
  vi.unstubAllGlobals();
});

test("an open editor follows theme changes without replacing its draft or selection", async () => {
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
  document.documentElement.dataset.theme = "obsidian-linear";
  const draft = "const unsavedDraft = true;";
  const { container } = render(
    <FileEditorSurface path="draft.ts" value={draft} dirty onChange={vi.fn()} onSave={vi.fn()} onClose={vi.fn()} />,
  );
  const editor = await waitFor(() => {
    const element = container.querySelector<HTMLElement>(".cm-content");
    expect(element).not.toBeNull();
    const view = EditorView.findFromDOM(element!);
    expect(view).not.toBeNull();
    return view!;
  });
  editor.dispatch({ selection: { anchor: 9 } });
  expect(editor.state.facet(EditorView.darkTheme)).toBe(true);

  for (const theme of ["paper-daylight", "obsidian-linear"]) {
    await act(async () => {
      document.documentElement.dataset.theme = theme;
    });
    await waitFor(() => expect(editor.state.facet(EditorView.darkTheme)).toBe(theme === "obsidian-linear"));
    expect(EditorView.findFromDOM(container.querySelector<HTMLElement>(".cm-content")!)).toBe(editor);
    expect(editor.state.doc.toString()).toBe(draft);
    expect(editor.state.selection.main.anchor).toBe(9);
  }
});
