import { type ComponentType, useEffect, useMemo, useState } from "react";
import { loadFileEditorExtensions } from "../utils/fileEditorLanguage";

type Props = {
  path: string;
  value: string;
  loading?: boolean;
  saving?: boolean;
  dirty?: boolean;
  canSave?: boolean;
  breakpointLines?: number[];
  currentLine?: number | null;
  statusText?: string;
  error?: string;
  hideHeader?: boolean;
  onToggleBreakpoint?: (line: number) => void;
  onResolveDefinition?: (input: { path: string; line: number; column: number; symbol?: string }) => void;
  onChange: (value: string) => void;
  onSave: () => void;
  onClose: () => void;
};

type CodeMirrorComponent = ComponentType<{
  value: string;
  className?: string;
  height?: string;
  width?: string;
  theme?: "light" | "dark";
  extensions?: unknown[];
  autoFocus?: boolean;
  editable?: boolean;
  basicSetup?: unknown;
  onCreateEditor?: (view: import("@codemirror/view").EditorView) => void;
  onChange?: (value: string) => void;
}>;

type CodeMirrorEditorView = import("@codemirror/view").EditorView;

const EMPTY_BREAKPOINT_LINES: number[] = [];
const FILE_EDITOR_BASIC_SETUP = {
  lineNumbers: true,
  foldGutter: true,
  highlightActiveLineGutter: true,
};

type EditorRuntime = {
  CodeMirrorEditor: CodeMirrorComponent;
  languageExtensions: unknown[];
  stateModule: typeof import("@codemirror/state");
  viewModule: typeof import("@codemirror/view");
};

function createEditorTheme(
  EditorView: typeof import("@codemirror/view").EditorView,
  themeMode: "light" | "dark",
) {
  return EditorView.theme({
    "&": {
      backgroundColor: "var(--editor-bg)",
      color: "var(--editor-text)",
      fontFamily: "var(--editor-font-family)",
      fontSize: "var(--editor-font-size)",
      lineHeight: "var(--editor-line-height)",
    },
    ".cm-scroller": {
      fontFamily: "var(--editor-font-family)",
      fontSize: "var(--editor-font-size)",
      lineHeight: "var(--editor-line-height)",
    },
    ".cm-content": {
      caretColor: "var(--editor-text)",
      fontFamily: "var(--editor-font-family)",
      fontSize: "var(--editor-font-size)",
      lineHeight: "var(--editor-line-height)",
    },
    ".cm-gutters": {
      backgroundColor: "var(--editor-gutter-bg)",
      color: "var(--editor-gutter-text)",
      borderRight: "1px solid var(--border)",
      fontFamily: "var(--editor-font-family)",
      fontSize: "var(--editor-font-size)",
      lineHeight: "var(--editor-line-height)",
    },
    ".cm-activeLine, .cm-activeLineGutter": {
      backgroundColor: "var(--accent-soft)",
    },
    ".cm-selectionBackground, &.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground": {
      backgroundColor: "var(--accent-soft-strong)",
    },
    ".cm-cursor, .cm-dropCursor": {
      borderLeftColor: "var(--editor-text)",
    },
  }, { dark: themeMode === "dark" });
}

function createDebugExtensions(
  viewModule: typeof import("@codemirror/view"),
  stateModule: typeof import("@codemirror/state"),
  breakpointLines: number[],
  currentLine: number | null,
  onToggleBreakpoint?: (line: number) => void,
) {
  const { Decoration, EditorView, GutterMarker, gutter } = viewModule;
  const { RangeSetBuilder } = stateModule;
  const activeBreakpoints = Array.from(new Set(breakpointLines.filter((line) => line > 0))).sort((left, right) => left - right);
  const BreakpointMarker = class extends GutterMarker {
    toDOM() {
      const dot = document.createElement("span");
      dot.className = "cm-debug-breakpoint-marker";
      return dot;
    }
  };
  const marker = new BreakpointMarker();
  const extensions: unknown[] = [
    gutter({
      class: "cm-debug-breakpoint-gutter",
      markers(view) {
        const builder = new RangeSetBuilder<InstanceType<typeof BreakpointMarker>>();
        activeBreakpoints.forEach((lineNumber) => {
          if (lineNumber > view.state.doc.lines) {
            return;
          }
          const line = view.state.doc.line(lineNumber);
          builder.add(line.from, line.from, marker);
        });
        return builder.finish();
      },
      domEventHandlers: onToggleBreakpoint ? {
        mousedown(view, block, event) {
          event.preventDefault();
          onToggleBreakpoint(view.state.doc.lineAt(block.from).number);
          return true;
        },
      } : {},
    }),
    EditorView.baseTheme({
      ".cm-debug-breakpoint-gutter": {
        width: "16px",
      },
      ".cm-debug-breakpoint-marker": {
        display: "inline-block",
        width: "10px",
        height: "10px",
        borderRadius: "9999px",
        backgroundColor: "#dc2626",
        boxShadow: "0 0 0 1px rgba(255, 255, 255, 0.15)",
      },
      ".cm-debug-current-line": {
        backgroundColor: "rgba(56, 189, 248, 0.14)",
      },
    }),
  ];

  if (currentLine && currentLine > 0) {
    extensions.push(EditorView.decorations.of((view) => {
      const builder = new RangeSetBuilder<import("@codemirror/view").Decoration>();
      if (currentLine > view.state.doc.lines) {
        return builder.finish();
      }
      const line = view.state.doc.line(currentLine);
      builder.add(line.from, line.from, Decoration.line({ class: "cm-debug-current-line" }));
      return builder.finish();
    }));
  }

  return extensions;
}

function isSymbolChar(char: string) {
  return /[A-Za-z0-9_$]/.test(char);
}

function extractSymbolAt(text: string, index: number) {
  if (!text) {
    return "";
  }
  const boundedIndex = Math.min(Math.max(index, 0), text.length - 1);
  if (!isSymbolChar(text[boundedIndex] || "")) {
    return "";
  }
  let start = boundedIndex;
  let end = boundedIndex;
  while (start > 0 && isSymbolChar(text[start - 1] || "")) {
    start -= 1;
  }
  while (end + 1 < text.length && isSymbolChar(text[end + 1] || "")) {
    end += 1;
  }
  return text.slice(start, end + 1);
}

function resolveTextareaDefinitionTarget(
  path: string,
  value: string,
  offset: number,
) {
  const boundedOffset = Math.min(Math.max(offset, 0), value.length);
  const before = value.slice(0, boundedOffset);
  const line = before.split(/\r?\n/).length;
  const lineStart = before.lastIndexOf("\n") + 1;
  const column = boundedOffset - lineStart + 1;
  const lineEnd = value.indexOf("\n", boundedOffset);
  const currentLineText = value.slice(lineStart, lineEnd === -1 ? value.length : lineEnd);
  const symbol = extractSymbolAt(currentLineText, Math.max(0, column - 1));
  return {
    path,
    line,
    column,
    ...(symbol ? { symbol } : {}),
  };
}

function resolveEditorDefinitionTarget(
  view: CodeMirrorEditorView,
  path: string,
  clientX: number,
  clientY: number,
) {
  const position = view.posAtCoords({ x: clientX, y: clientY });
  if (position === null) {
    return null;
  }
  const lineInfo = view.state.doc.lineAt(position);
  const column = position - lineInfo.from + 1;
  const symbol = extractSymbolAt(lineInfo.text, Math.max(0, column - 1));
  return {
    path,
    line: lineInfo.number,
    column,
    ...(symbol ? { symbol } : {}),
  };
}

export function FileEditorSurface({
  path,
  value,
  loading = false,
  saving = false,
  dirty = false,
  canSave = false,
  breakpointLines,
  currentLine = null,
  statusText = "",
  error = "",
  hideHeader = false,
  onToggleBreakpoint,
  onResolveDefinition,
  onChange,
  onSave,
  onClose,
}: Props) {
  const [editorRuntime, setEditorRuntime] = useState<EditorRuntime | null>(null);
  const [editorView, setEditorView] = useState<CodeMirrorEditorView | null>(null);
  const canUseCodeMirror = typeof window !== "undefined" && typeof window.ResizeObserver !== "undefined";
  const codeMirrorTheme = typeof document !== "undefined" && document.documentElement.dataset.theme === "classic"
    ? "light"
    : "dark";
  const normalizedBreakpointLines = breakpointLines ?? EMPTY_BREAKPOINT_LINES;

  useEffect(() => {
    let active = true;
    if (!canUseCodeMirror) {
      setEditorRuntime(null);
      setEditorView(null);
      return () => {
        active = false;
      };
    }

    void Promise.all([
      import("@uiw/react-codemirror"),
      loadFileEditorExtensions(path),
      import("@codemirror/state"),
      import("@codemirror/view"),
    ])
      .then(([module, languageExtensions, stateModule, viewModule]) => {
        if (!active) {
          return;
        }
        setEditorRuntime({
          CodeMirrorEditor: module.default as CodeMirrorComponent,
          languageExtensions,
          stateModule,
          viewModule,
        });
      })
      .catch(() => {
        if (!active) {
          return;
        }
        setEditorRuntime(null);
        setEditorView(null);
      });

    return () => {
      active = false;
    };
  }, [canUseCodeMirror, path]);

  const editorExtensions = useMemo(() => {
    if (!editorRuntime) {
      return [];
    }
    return [
      ...editorRuntime.languageExtensions,
      ...createDebugExtensions(
        editorRuntime.viewModule,
        editorRuntime.stateModule,
        normalizedBreakpointLines,
        currentLine,
        onToggleBreakpoint,
      ),
      createEditorTheme(editorRuntime.viewModule.EditorView, codeMirrorTheme),
    ];
  }, [codeMirrorTheme, currentLine, editorRuntime, normalizedBreakpointLines, onToggleBreakpoint]);

  const CodeMirrorEditor = editorRuntime?.CodeMirrorEditor ?? null;

  useEffect(() => {
    if (!editorView || !currentLine || currentLine <= 0) {
      return;
    }
    if (currentLine > editorView.state.doc.lines) {
      return;
    }
    const line = editorView.state.doc.line(currentLine);
    const lineBlock = editorView.lineBlockAt(line.from);
    const targetTop = Math.max(0, lineBlock.top - editorView.scrollDOM.clientHeight / 2);
    if (typeof editorView.scrollDOM.scrollTo === "function") {
      editorView.scrollDOM.scrollTo({ top: targetTop });
      return;
    }
    editorView.scrollDOM.scrollTop = targetTop;
  }, [currentLine, editorView]);

  useEffect(() => {
    if (!canSave || loading || saving || typeof window === "undefined") {
      return undefined;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        onSave();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [canSave, loading, onSave, saving]);
  return (
    <section className="flex h-full min-h-0 flex-1 flex-col overflow-hidden bg-[var(--surface)]">
      {!hideHeader ? (
        <div className="border-b border-[var(--border)] bg-[var(--surface-strong)] px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <h2 className="truncate text-base font-semibold text-[var(--text)]">{path}</h2>
              <p className="text-xs text-[var(--muted)]">{dirty ? "有未保存修改" : "已与磁盘同步"}</p>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm hover:bg-[var(--surface)]"
              >
                返回
              </button>
              <button
                type="button"
                onClick={onSave}
                disabled={loading || saving || !canSave}
                className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm text-white disabled:opacity-60"
              >
                {saving ? "保存中..." : "保存"}
              </button>
            </div>
          </div>
          {statusText ? <p className="mt-2 text-sm text-[var(--muted)]">{statusText}</p> : null}
          {error ? <p className="mt-2 text-sm text-red-600">{error}</p> : null}
        </div>
      ) : null}
      <div className="min-h-0 flex-1 overflow-hidden">
        {CodeMirrorEditor ? (
          <div
            key={path}
            data-testid="file-editor-host"
            className="file-editor-surface flex h-full min-h-0 min-w-0 overflow-hidden bg-[var(--editor-bg)] text-[var(--editor-text)]"
            onMouseDown={(event) => {
              if (!onResolveDefinition || !editorView || event.button !== 0 || (!event.ctrlKey && !event.metaKey)) {
                return;
              }
              const target = event.target;
              if (target instanceof HTMLElement && target.closest(".cm-gutters")) {
                return;
              }
              const definitionTarget = resolveEditorDefinitionTarget(editorView, path, event.clientX, event.clientY);
              if (!definitionTarget) {
                return;
              }
              event.preventDefault();
              onResolveDefinition(definitionTarget);
            }}
          >
            <CodeMirrorEditor
              key={path}
              value={value}
              className="h-full min-h-0 w-full min-w-0"
              height="100%"
              width="100%"
              theme={codeMirrorTheme}
              extensions={editorExtensions}
              autoFocus
              editable={!loading && !saving}
              onCreateEditor={(view) => {
                setEditorView(view);
              }}
              basicSetup={FILE_EDITOR_BASIC_SETUP}
              onChange={onChange}
            />
          </div>
        ) : (
          <textarea
            key={path}
            aria-label="文件内容"
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onClick={(event) => {
              if (!onResolveDefinition || event.button !== 0 || (!event.ctrlKey && !event.metaKey)) {
                return;
              }
              const selectionStart = event.currentTarget.selectionStart ?? 0;
              onResolveDefinition(resolveTextareaDefinitionTarget(path, value, selectionStart));
            }}
            spellCheck={false}
            style={{
              fontFamily: "var(--editor-font-family)",
              fontSize: "var(--editor-font-size)",
              lineHeight: "var(--editor-line-height)",
              touchAction: "pan-x pan-y",
              overscrollBehavior: "contain",
              scrollbarGutter: "stable both-edges",
              WebkitOverflowScrolling: "touch",
            }}
            className="block h-full min-h-0 w-full resize-none overflow-auto border-0 bg-[var(--editor-bg)] p-4 text-[var(--editor-text)] outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent)]"
          />
        )}
      </div>
    </section>
  );
}
