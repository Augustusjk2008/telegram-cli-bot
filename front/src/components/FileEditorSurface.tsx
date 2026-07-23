import { MoreHorizontal } from "lucide-react";
import { type ComponentType, type KeyboardEvent as ReactKeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import * as codemirrorState from "@codemirror/state";
import type { Extension } from "@codemirror/state";
import * as codemirrorView from "@codemirror/view";
import { tags } from "@lezer/highlight";
import type { CodeNavigationIntent, CodeNavigationKind } from "../services/types";
import { isLightUiTheme } from "../theme";
import { createFileEditorInlineCompletion, type FileEditorInlineCompletionOptions } from "../utils/fileEditorInlineCompletion";
import { loadFileEditorExtensions } from "../utils/fileEditorLanguage";

type Props = {
  path: string;
  value: string;
  loading?: boolean;
  saving?: boolean;
  dirty?: boolean;
  canSave?: boolean;
  readOnly?: boolean;
  breakpointLines?: number[];
  currentLine?: number | null;
  reveal?: { line: number; column: number; requestId: string } | null;
  navigationCommand?: { kind: CodeNavigationKind; requestId: string } | null;
  canNavigateImplementation?: boolean;
  statusText?: string;
  error?: string;
  hideHeader?: boolean;
  inlineCompletion?: FileEditorInlineCompletionOptions;
  onToggleBreakpoint?: (line: number) => void;
  onResolveCodeNavigation?: (input: CodeNavigationIntent) => void;
  onChange: (value: string) => void;
  onSave: () => void;
  onClose: () => void;
};

type CodeMirrorComponent = ComponentType<{
  value: string;
  className?: string;
  height?: string;
  width?: string;
  theme?: "light" | "dark" | "none";
  extensions?: Extension[];
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
const FILE_EDITOR_HIGHLIGHT_STYLE = HighlightStyle.define([
  { tag: tags.comment, color: "var(--editor-syntax-comment)", fontStyle: "italic" },
  {
    tag: [tags.keyword, tags.modifier, tags.operatorKeyword],
    color: "var(--editor-syntax-keyword)",
  },
  {
    tag: [tags.string, tags.special(tags.string)],
    color: "var(--editor-syntax-string)",
  },
  {
    tag: [tags.number, tags.bool, tags.atom],
    color: "var(--editor-syntax-number)",
  },
  {
    tag: [tags.typeName, tags.className, tags.namespace],
    color: "var(--editor-syntax-type)",
  },
  {
    tag: [
      tags.function(tags.variableName),
      tags.function(tags.propertyName),
      tags.function(tags.definition(tags.variableName)),
    ],
    color: "var(--editor-syntax-function)",
  },
  {
    tag: [tags.meta, tags.macroName],
    color: "var(--editor-syntax-meta)",
  },
  {
    tag: tags.invalid,
    color: "var(--editor-syntax-invalid)",
    textDecoration: "underline wavy",
  },
]);
const FILE_EDITOR_SYNTAX_HIGHLIGHTING = syntaxHighlighting(FILE_EDITOR_HIGHLIGHT_STYLE);

type EditorRuntime = {
  CodeMirrorEditor: CodeMirrorComponent;
  languageExtensions: Extension[];
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
      fontSize: "var(--editor-gutter-font-size)",
      lineHeight: "var(--editor-line-height)",
    },
    ".cm-activeLine": {
      backgroundColor: "var(--editor-active-line-bg)",
    },
    ".cm-activeLineGutter": {
      backgroundColor: "var(--editor-active-line-gutter-bg)",
    },
    ".cm-selectionBackground, &.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground": {
      backgroundColor: "var(--editor-selection-bg)",
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
  const extensions: Extension[] = [
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

function resolveTextareaNavigationTarget(
  path: string,
  value: string,
  offset: number,
  kind: CodeNavigationKind,
) {
  const boundedOffset = Math.min(Math.max(offset, 0), value.length);
  const before = value.slice(0, boundedOffset);
  const line = before.split(/\r?\n/).length;
  const lineStart = before.lastIndexOf("\n") + 1;
  const utf16ColumnOffset = boundedOffset - lineStart;
  const column = Array.from(value.slice(lineStart, boundedOffset)).length + 1;
  const lineEnd = value.indexOf("\n", boundedOffset);
  const currentLineText = value.slice(lineStart, lineEnd === -1 ? value.length : lineEnd);
  const symbol = extractSymbolAt(currentLineText, Math.max(0, utf16ColumnOffset));
  return {
    kind,
    path,
    line,
    column,
    ...(symbol ? { symbol } : {}),
  };
}

function resolveEditorNavigationTargetAtPosition(
  view: CodeMirrorEditorView,
  path: string,
  position: number,
  kind: CodeNavigationKind,
) {
  const lineInfo = view.state.doc.lineAt(position);
  const utf16ColumnOffset = position - lineInfo.from;
  const column = Array.from(lineInfo.text.slice(0, utf16ColumnOffset)).length + 1;
  const symbol = extractSymbolAt(lineInfo.text, Math.max(0, utf16ColumnOffset));
  return {
    kind,
    path,
    line: lineInfo.number,
    column,
    ...(symbol ? { symbol } : {}),
  };
}

function resolveEditorNavigationTargetAtCoordinates(
  view: CodeMirrorEditorView,
  path: string,
  clientX: number,
  clientY: number,
  kind: CodeNavigationKind,
) {
  const position = view.posAtCoords({ x: clientX, y: clientY });
  if (position === null) {
    return null;
  }
  return resolveEditorNavigationTargetAtPosition(view, path, position, kind);
}

function textOffsetAtPosition(value: string, line: number, column: number) {
  if (line <= 0 || column <= 0) {
    return null;
  }
  const lineStarts = [0];
  for (let index = 0; index < value.length; index += 1) {
    if (value[index] === "\n") {
      lineStarts.push(index + 1);
    }
  }
  if (line > lineStarts.length) {
    return null;
  }
  const start = lineStarts[line - 1];
  const nextStart = lineStarts[line];
  let end = typeof nextStart === "number" ? nextStart - 1 : value.length;
  if (end > start && value[end - 1] === "\r") {
    end -= 1;
  }
  const lineText = value.slice(start, end);
  const prefix = Array.from(lineText).slice(0, Math.max(0, column - 1)).join("");
  return Math.min(start + prefix.length, end);
}

export function FileEditorSurface({
  path,
  value,
  loading = false,
  saving = false,
  dirty = false,
  canSave = false,
  readOnly = false,
  breakpointLines,
  currentLine = null,
  reveal = null,
  navigationCommand = null,
  canNavigateImplementation = true,
  statusText = "",
  error = "",
  hideHeader = false,
  inlineCompletion,
  onToggleBreakpoint,
  onResolveCodeNavigation,
  onChange,
  onSave,
  onClose,
}: Props) {
  const [editorRuntime, setEditorRuntime] = useState<EditorRuntime | null>(null);
  const [editorView, setEditorView] = useState<CodeMirrorEditorView | null>(null);
  const [navigationMenuOpen, setNavigationMenuOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const canUseCodeMirror = typeof window !== "undefined" && typeof window.ResizeObserver !== "undefined";
  const codeMirrorTheme = typeof document !== "undefined" && isLightUiTheme(document.documentElement.dataset.theme)
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
    ])
      .then(([module, languageExtensions]) => {
        if (!active) {
          return;
        }
        setEditorRuntime({
          CodeMirrorEditor: module.default as CodeMirrorComponent,
          languageExtensions: languageExtensions as Extension[],
          stateModule: codemirrorState,
          viewModule: codemirrorView,
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
    const extensions = [
      ...editorRuntime.languageExtensions,
      FILE_EDITOR_SYNTAX_HIGHLIGHTING,
      ...createDebugExtensions(
        editorRuntime.viewModule,
        editorRuntime.stateModule,
        normalizedBreakpointLines,
        currentLine,
        onToggleBreakpoint,
      ),
      createEditorTheme(editorRuntime.viewModule.EditorView, codeMirrorTheme),
    ];
    if (inlineCompletion) {
      extensions.push(...createFileEditorInlineCompletion(inlineCompletion));
    }
    return extensions;
  }, [codeMirrorTheme, currentLine, editorRuntime, inlineCompletion, normalizedBreakpointLines, onToggleBreakpoint]);

  const CodeMirrorEditor = editorRuntime?.CodeMirrorEditor ?? null;

  useEffect(() => {
    setNavigationMenuOpen(false);
  }, [path]);

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
    if (!reveal) {
      return;
    }
    if (editorView) {
      if (reveal.line <= 0 || reveal.line > editorView.state.doc.lines) {
        return;
      }
      const lineInfo = editorView.state.doc.line(reveal.line);
      const position = Math.min(lineInfo.to, lineInfo.from + Math.max(0, reveal.column - 1));
      editorView.dispatch({
        selection: { anchor: position },
        effects: codemirrorView.EditorView.scrollIntoView(position, { y: "center" }),
      });
      editorView.focus();
      return;
    }

    const textarea = textareaRef.current;
    const position = textOffsetAtPosition(value, reveal.line, reveal.column);
    if (!textarea || position === null) {
      return;
    }
    textarea.setSelectionRange(position, position);
    textarea.focus();
    const lineHeight = Number.parseFloat(window.getComputedStyle(textarea).lineHeight) || 20;
    textarea.scrollTop = Math.max(0, (reveal.line - 1) * lineHeight - textarea.clientHeight / 2);
  }, [editorView, reveal?.requestId]);

  function requestCodeNavigation(kind: CodeNavigationKind) {
    if (!onResolveCodeNavigation || (kind === "implementation" && !canNavigateImplementation)) {
      return false;
    }
    const target = editorView
      ? resolveEditorNavigationTargetAtPosition(editorView, path, editorView.state.selection.main.head, kind)
      : textareaRef.current
        ? resolveTextareaNavigationTarget(path, value, textareaRef.current.selectionStart ?? 0, kind)
        : null;
    if (!target) {
      return false;
    }
    onResolveCodeNavigation(target);
    return true;
  }

  function handleCodeNavigationKeyDown(event: ReactKeyboardEvent<HTMLElement>) {
    if (event.key !== "F12" || event.altKey || event.shiftKey) {
      return;
    }
    const kind = event.ctrlKey || event.metaKey ? "implementation" : "definition";
    if (requestCodeNavigation(kind)) {
      event.preventDefault();
    }
  }

  useEffect(() => {
    if (navigationCommand) {
      requestCodeNavigation(navigationCommand.kind);
    }
  }, [navigationCommand?.requestId]);

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
                className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm text-[var(--accent-foreground)] disabled:opacity-60"
              >
                {saving ? "保存中..." : "保存"}
              </button>
            </div>
          </div>
          {statusText ? <p className="mt-2 text-sm text-[var(--muted)]">{statusText}</p> : null}
          {error ? <p className="mt-2 text-sm text-red-600">{error}</p> : null}
        </div>
      ) : null}
      <div className="relative min-h-0 flex-1 overflow-hidden">
        {CodeMirrorEditor ? (
          <div
            key={path}
            data-testid="file-editor-host"
            className="file-editor-surface flex h-full min-h-0 min-w-0 overflow-hidden bg-[var(--editor-bg)] text-[var(--editor-text)]"
            onKeyDown={handleCodeNavigationKeyDown}
            onMouseDown={(event) => {
              if (!onResolveCodeNavigation || !editorView || event.button !== 0 || (!event.ctrlKey && !event.metaKey)) {
                return;
              }
              const target = event.target;
              if (target instanceof HTMLElement && target.closest(".cm-gutters")) {
                return;
              }
              const definitionTarget = resolveEditorNavigationTargetAtCoordinates(
                editorView,
                path,
                event.clientX,
                event.clientY,
                "definition",
              );
              if (!definitionTarget) {
                return;
              }
              event.preventDefault();
              onResolveCodeNavigation(definitionTarget);
            }}
          >
            <CodeMirrorEditor
              key={path}
              value={value}
              className="h-full min-h-0 w-full min-w-0"
              height="100%"
              width="100%"
              theme="none"
              extensions={editorExtensions}
              autoFocus
              editable={!loading && !saving && !readOnly}
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
            ref={textareaRef}
            aria-label="文件内容"
            value={value}
            readOnly={readOnly}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={handleCodeNavigationKeyDown}
            onClick={(event) => {
              if (!onResolveCodeNavigation || event.button !== 0 || (!event.ctrlKey && !event.metaKey)) {
                return;
              }
              const selectionStart = event.currentTarget.selectionStart ?? 0;
              onResolveCodeNavigation(resolveTextareaNavigationTarget(path, value, selectionStart, "definition"));
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
        {onResolveCodeNavigation ? (
          <div className="absolute right-3 top-3 z-10 md:hidden [@media(pointer:coarse)]:block">
            <button
              type="button"
              aria-label="编辑器操作"
              aria-haspopup="menu"
              aria-expanded={navigationMenuOpen}
              onClick={() => setNavigationMenuOpen((current) => !current)}
              className="inline-flex h-9 w-9 touch-manipulation items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--surface)] text-[var(--muted)] shadow-[var(--shadow-soft)]"
            >
              <MoreHorizontal className="h-4 w-4" />
            </button>
            {navigationMenuOpen ? (
              <div
                role="menu"
                aria-label="编辑器操作"
                className="absolute right-0 top-full mt-1 min-w-36 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-1 shadow-[var(--shadow-card)]"
              >
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setNavigationMenuOpen(false);
                    requestCodeNavigation("definition");
                  }}
                  className="flex w-full touch-manipulation rounded-md px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                >
                  转到定义
                </button>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setNavigationMenuOpen(false);
                    requestCodeNavigation("implementation");
                  }}
                  disabled={!canNavigateImplementation}
                  className="flex w-full touch-manipulation rounded-md px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  转到实现
                </button>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}
