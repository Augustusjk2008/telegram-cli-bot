import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { afterEach, expect, test, vi } from "vitest";
import { createFileEditorCodeNavigationHover } from "../utils/fileEditorCodeNavigation";

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

test("Ctrl-hover decorates a resolvable symbol as a definition link", async () => {
  vi.useFakeTimers();
  const request = vi.fn(async () => true);
  const parent = document.createElement("div");
  document.body.appendChild(parent);
  const doc = "const greet = 1;\ngreet();";
  const view = new EditorView({
    parent,
    state: EditorState.create({
      doc,
      extensions: createFileEditorCodeNavigationHover({ path: "app.ts", hoverDelayMs: 0, request }),
    }),
  });
  vi.spyOn(view, "posAtCoords").mockReturnValue(doc.lastIndexOf("greet") + 2);

  view.contentDOM.dispatchEvent(new MouseEvent("mousemove", {
    bubbles: true, clientX: 24, clientY: 24, ctrlKey: true,
  }));
  await vi.advanceTimersByTimeAsync(0);
  await Promise.resolve();

  expect(request).toHaveBeenCalledWith({
    kind: "definition", path: "app.ts", line: 2, column: 3, symbol: "greet",
  }, expect.any(AbortSignal));
  expect(parent.querySelector(".cm-code-navigation-link")?.textContent).toBe("greet");
  view.destroy();
});
