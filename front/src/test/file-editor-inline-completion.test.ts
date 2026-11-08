import { EditorState } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";
import { expect, test, vi } from "vitest";
import type { InlineCompletionRequest, InlineCompletionResult } from "../services/types";
import { createFileEditorInlineCompletion } from "../utils/fileEditorInlineCompletion";

test("Tab accepts an inline suggestion before the editor Tab binding", async () => {
  let resolveRequest: ((result: InlineCompletionResult) => void) | undefined;
  const request = vi.fn((input: InlineCompletionRequest) => new Promise<InlineCompletionResult>((resolve) => {
    resolveRequest = (result) => resolve(result);
  }));
  let fallbackRuns = 0;
  const view = new EditorView({
    parent: document.body,
    state: EditorState.create({
      doc: "const answer = ",
      selection: { anchor: "const answer = ".length },
      extensions: [
        ...createFileEditorInlineCompletion({
          editorId: "test-editor",
          path: "answer.ts",
          languageId: "typescript",
          autoTriggerEnabled: false,
          request,
        }),
        keymap.of([{
          key: "Tab",
          run() {
            fallbackRuns += 1;
            return true;
          },
        }]),
      ],
    }),
  });

  try {
    view.contentDOM.dispatchEvent(new KeyboardEvent("keydown", {
      altKey: true,
      bubbles: true,
      cancelable: true,
      code: "Backslash",
      key: "\\",
    }));
    expect(request).toHaveBeenCalledTimes(1);

    const [[{ requestId }]] = request.mock.calls;
    resolveRequest?.({
      requestId,
      model: "test-model",
      items: [{ insertText: "42\n  + 1" }],
      latencyMs: 1,
      context: { relatedFiles: [], truncated: false },
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    await vi.waitFor(() => expect(view.dom.querySelector(".cm-ai-inline-ghost")).toHaveTextContent("42"));
    expect(view.dom.querySelector(".cm-ai-inline-ghost")?.textContent).toBe("42");

    view.contentDOM.dispatchEvent(new KeyboardEvent("keydown", {
      bubbles: true,
      cancelable: true,
      code: "Tab",
      key: "Tab",
    }));

    expect(view.state.doc.toString()).toBe("const answer = 42\n  + 1");
    expect(fallbackRuns).toBe(0);

    view.contentDOM.dispatchEvent(new KeyboardEvent("keydown", {
      bubbles: true,
      cancelable: true,
      code: "Tab",
      key: "Tab",
    }));
    expect(fallbackRuns).toBe(1);
  } finally {
    view.destroy();
  }
});
