import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { afterEach, expect, test, vi } from "vitest";
import { createFileEditorInlineCompletion } from "../utils/fileEditorInlineCompletion";

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

test("inline completion extension requests and renders ghost text", async () => {
  vi.useFakeTimers();
  const request = vi.fn(async (input) => ({
    requestId: input.requestId,
    model: "coder",
    items: [{ insertText: " world", displayText: " world" }],
    latencyMs: 1,
    context: { relatedFiles: [], truncated: false },
  }));
  const parent = document.createElement("div");
  document.body.appendChild(parent);
  const view = new EditorView({
    parent,
    state: EditorState.create({
      doc: "hello",
      selection: { anchor: 5 },
      extensions: createFileEditorInlineCompletion({
        editorId: "editor-1",
        path: "app.ts",
        languageId: "typescript",
        autoTriggerDelayMs: 100,
        request,
      }),
    }),
  });

  view.dispatch({
    changes: { from: 5, insert: "!" },
    selection: { anchor: 6 },
    userEvent: "input.type",
  });
  await vi.advanceTimersByTimeAsync(120);
  await Promise.resolve();

  expect(request).toHaveBeenCalledWith(
    expect.objectContaining({
      editorId: "editor-1",
      path: "app.ts",
      languageId: "typescript",
      prefix: "hello!",
      trigger: "auto",
    }),
    expect.any(AbortSignal),
  );
  expect(parent.querySelector(".cm-ai-inline-ghost")?.textContent).toBe(" world");

  view.destroy();
});
