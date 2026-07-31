import { EditorState, StateEffect } from "@codemirror/state";
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
      extensions: createFileEditorCodeNavigationHover({
        path: "app.ts",
        hoverDelayMs: 0,
        request,
      }),
    }),
  });
  vi.spyOn(view, "posAtCoords").mockReturnValue(doc.lastIndexOf("greet") + 2);

  view.contentDOM.dispatchEvent(new MouseEvent("mousemove", {
    bubbles: true,
    clientX: 24,
    clientY: 24,
    ctrlKey: true,
  }));
  await vi.advanceTimersByTimeAsync(0);
  await Promise.resolve();

  expect(request).toHaveBeenCalledWith({
    kind: "definition",
    path: "app.ts",
    line: 2,
    column: 3,
    symbol: "greet",
  }, expect.any(AbortSignal));
  const link = parent.querySelector<HTMLElement>(".cm-code-navigation-link");
  expect(link?.textContent).toBe("greet");
  expect(link).toHaveAttribute("data-code-navigation-link", "true");
  expect(window.getComputedStyle(link as HTMLElement).cursor).toBe("pointer");
  expect(window.getComputedStyle(link as HTMLElement).textDecoration).toContain("underline");

  view.destroy();
});

test("releasing Ctrl removes the definition link decoration", async () => {
  vi.useFakeTimers();
  const parent = document.createElement("div");
  document.body.appendChild(parent);
  const doc = "greet();";
  const view = new EditorView({
    parent,
    state: EditorState.create({
      doc,
      extensions: createFileEditorCodeNavigationHover({
        path: "app.ts",
        hoverDelayMs: 0,
        request: async () => true,
      }),
    }),
  });
  vi.spyOn(view, "posAtCoords").mockReturnValue(2);

  view.contentDOM.dispatchEvent(new MouseEvent("mousemove", {
    bubbles: true,
    clientX: 24,
    clientY: 24,
    ctrlKey: true,
  }));
  await vi.advanceTimersByTimeAsync(0);
  await Promise.resolve();
  expect(parent.querySelector(".cm-code-navigation-link")).not.toBeNull();

  window.dispatchEvent(new KeyboardEvent("keyup", { key: "Control" }));

  expect(parent.querySelector(".cm-code-navigation-link")).toBeNull();
  view.destroy();
});

test("moving away aborts a pending probe and ignores its stale result", async () => {
  vi.useFakeTimers();
  let resolveProbe: ((available: boolean) => void) | undefined;
  let probeSignal: AbortSignal | undefined;
  const request = vi.fn((_input, signal: AbortSignal) => {
    probeSignal = signal;
    return new Promise<boolean>((resolve) => {
      resolveProbe = resolve;
    });
  });
  const parent = document.createElement("div");
  document.body.appendChild(parent);
  const doc = "greet(); ";
  const view = new EditorView({
    parent,
    state: EditorState.create({
      doc,
      extensions: createFileEditorCodeNavigationHover({
        path: "app.ts",
        hoverDelayMs: 0,
        request,
      }),
    }),
  });
  vi.spyOn(view, "posAtCoords")
    .mockReturnValueOnce(2)
    .mockReturnValueOnce(doc.length - 1);

  view.contentDOM.dispatchEvent(new MouseEvent("mousemove", {
    bubbles: true,
    clientX: 24,
    clientY: 24,
    ctrlKey: true,
  }));
  await vi.advanceTimersByTimeAsync(0);
  expect(request).toHaveBeenCalledTimes(1);

  view.contentDOM.dispatchEvent(new MouseEvent("mousemove", {
    bubbles: true,
    clientX: 64,
    clientY: 24,
    ctrlKey: true,
  }));

  expect(probeSignal?.aborted).toBe(true);
  resolveProbe?.(true);
  await Promise.resolve();
  expect(parent.querySelector(".cm-code-navigation-link")).toBeNull();

  view.destroy();
});

test("document changes clear the link and require a fresh probe", async () => {
  vi.useFakeTimers();
  const request = vi.fn(async () => true);
  const parent = document.createElement("div");
  document.body.appendChild(parent);
  const view = new EditorView({
    parent,
    state: EditorState.create({
      doc: "greet();",
      extensions: createFileEditorCodeNavigationHover({
        path: "app.ts",
        hoverDelayMs: 0,
        request,
      }),
    }),
  });
  vi.spyOn(view, "posAtCoords").mockReturnValue(2);
  const hover = () => view.contentDOM.dispatchEvent(new MouseEvent("mousemove", {
    bubbles: true,
    clientX: 24,
    clientY: 24,
    ctrlKey: true,
  }));

  hover();
  await vi.advanceTimersByTimeAsync(0);
  await Promise.resolve();
  expect(parent.querySelector(".cm-code-navigation-link")).not.toBeNull();

  view.dispatch({ changes: { from: view.state.doc.length, insert: " " } });
  expect(parent.querySelector(".cm-code-navigation-link")).toBeNull();
  hover();
  await vi.advanceTimersByTimeAsync(0);
  await Promise.resolve();

  expect(request).toHaveBeenCalledTimes(2);
  view.destroy();
});

test("leaving the editor clears the definition link", async () => {
  vi.useFakeTimers();
  const parent = document.createElement("div");
  document.body.appendChild(parent);
  const view = new EditorView({
    parent,
    state: EditorState.create({
      doc: "greet();",
      extensions: createFileEditorCodeNavigationHover({
        path: "app.ts",
        hoverDelayMs: 0,
        request: async () => true,
      }),
    }),
  });
  vi.spyOn(view, "posAtCoords").mockReturnValue(2);

  view.contentDOM.dispatchEvent(new MouseEvent("mousemove", {
    bubbles: true,
    clientX: 24,
    clientY: 24,
    ctrlKey: true,
  }));
  await vi.advanceTimersByTimeAsync(0);
  await Promise.resolve();
  expect(parent.querySelector(".cm-code-navigation-link")).not.toBeNull();

  view.contentDOM.dispatchEvent(new MouseEvent("mouseleave", { bubbles: true, ctrlKey: true }));

  expect(parent.querySelector(".cm-code-navigation-link")).toBeNull();
  view.destroy();
});

test("an unavailable definition never decorates the symbol", async () => {
  vi.useFakeTimers();
  const parent = document.createElement("div");
  document.body.appendChild(parent);
  const view = new EditorView({
    parent,
    state: EditorState.create({
      doc: "greet();",
      extensions: createFileEditorCodeNavigationHover({
        path: "app.ts",
        hoverDelayMs: 0,
        request: async () => false,
      }),
    }),
  });
  vi.spyOn(view, "posAtCoords").mockReturnValue(2);

  view.contentDOM.dispatchEvent(new MouseEvent("mousemove", {
    bubbles: true,
    clientX: 24,
    clientY: 24,
    ctrlKey: true,
  }));
  await vi.advanceTimersByTimeAsync(0);
  await Promise.resolve();

  expect(parent.querySelector(".cm-code-navigation-link")).toBeNull();
  view.destroy();
});

test("replacing the Ctrl-hover extension discards its previous link decoration", async () => {
  vi.useFakeTimers();
  const parent = document.createElement("div");
  document.body.appendChild(parent);
  const doc = "greet();";
  const view = new EditorView({
    parent,
    state: EditorState.create({
      doc,
      extensions: createFileEditorCodeNavigationHover({
        path: "app.ts",
        hoverDelayMs: 0,
        request: async () => true,
      }),
    }),
  });
  vi.spyOn(view, "posAtCoords").mockReturnValue(2);

  view.contentDOM.dispatchEvent(new MouseEvent("mousemove", {
    bubbles: true,
    clientX: 24,
    clientY: 24,
    ctrlKey: true,
  }));
  await vi.advanceTimersByTimeAsync(0);
  await Promise.resolve();
  expect(parent.querySelector(".cm-code-navigation-link")).not.toBeNull();

  view.dispatch({
    effects: StateEffect.reconfigure.of(createFileEditorCodeNavigationHover({
      path: "app.ts",
      hoverDelayMs: 20,
      request: async () => true,
    })),
  });

  expect(parent.querySelector(".cm-code-navigation-link")).toBeNull();
  view.destroy();
});

test("window blur clears the Ctrl-hover definition link", async () => {
  vi.useFakeTimers();
  const parent = document.createElement("div");
  document.body.appendChild(parent);
  const view = new EditorView({
    parent,
    state: EditorState.create({
      doc: "greet();",
      extensions: createFileEditorCodeNavigationHover({
        path: "app.ts",
        hoverDelayMs: 0,
        request: async () => true,
      }),
    }),
  });
  vi.spyOn(view, "posAtCoords").mockReturnValue(2);

  view.contentDOM.dispatchEvent(new MouseEvent("mousemove", {
    bubbles: true,
    clientX: 24,
    clientY: 24,
    ctrlKey: true,
  }));
  await vi.advanceTimersByTimeAsync(0);
  await Promise.resolve();
  expect(parent.querySelector(".cm-code-navigation-link")).not.toBeNull();

  window.dispatchEvent(new Event("blur"));

  expect(parent.querySelector(".cm-code-navigation-link")).toBeNull();
  view.destroy();
});
