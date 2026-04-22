import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, afterEach, expect, test, vi } from "vitest";
import { FileEditorSurface } from "../components/FileEditorSurface";

const codemirrorMockState = vi.hoisted(() => ({
  view: null as {
    posAtCoords: (coords: { x: number; y: number }) => number | null;
    state: {
      doc: {
        lineAt: (pos: number) => { from: number; number: number; text: string };
      };
    };
  } | null,
}));

vi.mock("../utils/fileEditorLanguage", () => ({
  loadFileEditorExtensions: vi.fn(async () => []),
}));

vi.mock("@uiw/react-codemirror", async () => {
  const React = await import("react");

  return {
    default: ({
      className,
      onCreateEditor,
    }: {
      className?: string;
      onCreateEditor?: (view: unknown) => void;
    }) => {
      React.useEffect(() => {
        if (codemirrorMockState.view) {
          onCreateEditor?.(codemirrorMockState.view);
        }
      }, [onCreateEditor]);

      return (
        <div className={className} data-testid="mock-codemirror">
          mock codemirror
        </div>
      );
    },
  };
});

beforeEach(() => {
  document.documentElement.dataset.theme = "deep-space";
  codemirrorMockState.view = {
    posAtCoords: () => 19,
    state: {
      doc: {
        lineAt: () => ({
          from: 18,
          number: 2,
          text: "run()",
        }),
      },
    },
  };
  vi.stubGlobal(
    "ResizeObserver",
    class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("ctrl click in codemirror asks parent to resolve the current symbol", async () => {
  const onResolveDefinition = vi.fn();

  render(
    <FileEditorSurface
      path="src/app.py"
      value={"from service import run\nrun()\n"}
      hideHeader
      onResolveDefinition={onResolveDefinition}
      onChange={() => {}}
      onSave={() => {}}
      onClose={() => {}}
    />,
  );

  const host = await screen.findByTestId("file-editor-host");
  fireEvent.mouseDown(host, {
    button: 0,
    ctrlKey: true,
    clientX: 24,
    clientY: 16,
  });

  expect(onResolveDefinition).toHaveBeenCalledWith({
    path: "src/app.py",
    line: 2,
    column: 2,
    symbol: "run",
  });
});

test("cmd click in textarea fallback also resolves the current symbol", () => {
  vi.unstubAllGlobals();
  const onResolveDefinition = vi.fn();

  render(
    <FileEditorSurface
      path="src/app.py"
      value={"run()\n"}
      hideHeader
      onResolveDefinition={onResolveDefinition}
      onChange={() => {}}
      onSave={() => {}}
      onClose={() => {}}
    />,
  );

  const textarea = screen.getByLabelText("文件内容") as HTMLTextAreaElement;
  textarea.setSelectionRange(1, 1);
  fireEvent.click(textarea, {
    button: 0,
    metaKey: true,
  });

  expect(onResolveDefinition).toHaveBeenCalledWith({
    path: "src/app.py",
    line: 1,
    column: 2,
    symbol: "run",
  });
});
