import { MoreHorizontal } from "lucide-react";
import { type ComponentType, type KeyboardEvent as ReactKeyboardEvent, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { foldGutter } from "@codemirror/language";
import { highlightSelectionMatches } from "@codemirror/search";
import * as codemirrorState from "@codemirror/state";
import type { Extension } from "@codemirror/state";
import * as codemirrorView from "@codemirror/view";
import type {
  CodeIntelligenceResult,
  CodeNavigationIntent,
  CodeNavigationIntentKind,
  CodePosition,
} from "../services/types";
import { useResolvedAppearance } from "../theme/appearanceRuntime";
import {
  createFileEditorCodeNavigationHover,
  extractFileEditorSymbolAt,
  resolveFileEditorNavigationTargetAtCoordinates,
  resolveFileEditorNavigationTargetAtPosition,
  type FileEditorCodeNavigationHoverOptions,
} from "../utils/fileEditorCodeNavigation";
import { FILE_EDITOR_SYNTAX_HIGHLIGHTING } from "../utils/fileEditorHighlight";
import { createFileEditorIndentGuides } from "../utils/fileEditorIndentGuides";
import { createFileEditorInlineCompletion, type FileEditorInlineCompletionOptions } from "../utils/fileEditorInlineCompletion";
import { inferFileEditorLanguageId, loadFileEditorExtensions } from "../utils/fileEditorLanguage";
import {
  createFileEditorLanguageFeatures,
  offsetToCodePosition,
  refreshFileEditorLanguageFeatures,
  type FileEditorLanguageFeatureOptions,
  type FileEditorLanguageFeatureQuery,
} from "../utils/fileEditorLanguageFeatures";
import { createFileEditorNameConventions } from "../utils/fileEditorNameConventions";
import { getFileEditorDocument, pruneFileEditorDocuments } from "../utils/fileEditorSession";
import { createFileEditorStickyScroll } from "../utils/fileEditorStickyScroll";

type Props = {
  path: string;
  value: string;
  sessionKey?: object;
  viewId?: string;
  active?: boolean;
  documentPaths?: readonly string[];
  loading?: boolean;
  saving?: boolean;
  dirty?: boolean;
  canSave?: boolean;
  readOnly?: boolean;
  breakpointLines?: number[];
  currentLine?: number | null;
  reveal?: { line: number; column: number; requestId: string } | null;
  navigationCommand?: { kind: CodeNavigationIntentKind; requestId: string } | null;
  canNavigateImplementation?: boolean;
  canFindReferences?: boolean;
  statusText?: string;
  error?: string;
  hideHeader?: boolean;
  inlineCompletion?: FileEditorInlineCompletionOptions;
  codeNavigationHover?: Omit<FileEditorCodeNavigationHoverOptions, "path"> & { contextKey?: unknown };
  /**
   * Language-server features. `request` is only called once `value` matches the text the editor
   * measured positions against; `refreshKey` changes when results should be refetched.
   */
  languageFeatures?: Omit<FileEditorLanguageFeatureOptions, "request"> & {
    request: (query: FileEditorLanguageFeatureQuery, signal: AbortSignal) => Promise<CodeIntelligenceResult | null>;
    refreshKey?: unknown;
  };
  onToggleBreakpoint?: (line: number) => void;
  onResolveCodeNavigation?: (input: CodeNavigationIntent) => void;
  onCursorChange?: (position: CodePosition) => void;
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
  // The fold gutter is added separately so its markers can stay hidden until the gutter is hovered.
  foldGutter: false,
  highlightActiveLineGutter: true,
};

function createFoldMarker(open: boolean) {
  const marker = document.createElement("span");
  marker.className = open ? "cm-fold-marker" : "cm-fold-marker cm-fold-marker-closed";
  marker.title = open ? "折叠" : "展开";
  return marker;
}

const LANGUAGE_FEATURE_SYNC_ATTEMPTS = 8;
const LANGUAGE_FEATURE_SYNC_INTERVAL_MS = 40;
const FILE_EDITOR_FOLD_GUTTER = foldGutter({ markerDOM: createFoldMarker });
const FILE_EDITOR_OCCURRENCES = highlightSelectionMatches({ highlightWordAroundCursor: true });

type EditorRuntime = {
  CodeMirrorEditor: CodeMirrorComponent;
  getDefaultExtensions: typeof import("@uiw/react-codemirror").getDefaultExtensions;
  languageExtensions: Extension[];
  stateModule: typeof import("@codemirror/state");
  viewModule: typeof import("@codemirror/view");
};

function SharedFileEditor({
  sessionKey,
  path,
  viewId,
  value,
  active,
  editable,
  readOnly,
  runtime,
  extensions,
  onChange,
  onCreateEditor,
}: {
  sessionKey: object;
  path: string;
  viewId: string;
  value: string;
  active: boolean;
  editable: boolean;
  readOnly: boolean;
  runtime: EditorRuntime;
  extensions: Extension[];
  onChange: (value: string) => void;
  onCreateEditor: (view: CodeMirrorEditorView | null) => void;
}) {
  const parentRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<CodeMirrorEditorView | null>(null);
  const onChangeRef = useRef(onChange);
  const mountedRef = useRef(false);
  const configuration = useMemo(() => new codemirrorState.Compartment(), []);
  const document = useMemo(() => getFileEditorDocument(sessionKey, path, value), [sessionKey, path]);
  const renderedRevision = document.revision;
  const configuredExtensions = useMemo(() => [
    ...runtime.getDefaultExtensions({
      theme: "none",
      editable,
      readOnly,
      basicSetup: { ...FILE_EDITOR_BASIC_SETUP, history: false, historyKeymap: false },
    }),
    codemirrorView.EditorView.theme({
      "&": { height: "100%", width: "100%" },
      ".cm-scroller": { height: "100% !important" },
    }),
    ...extensions,
  ], [document, editable, extensions, readOnly, runtime.getDefaultExtensions]);

  useLayoutEffect(() => {
    onChangeRef.current = onChange;
    document.synchronize(value, renderedRevision);
  }, [document, onChange, renderedRevision, value]);

  useLayoutEffect(() => {
    const view = document.createView(parentRef.current!, viewId, [configuration.of(configuredExtensions)], (text) => onChangeRef.current(text));
    viewRef.current = view;
    onCreateEditor(view);
    return () => {
      document.releaseView(view);
      viewRef.current = null;
      onCreateEditor(null);
    };
  }, [configuration, document, viewId, onCreateEditor]);

  useLayoutEffect(() => {
    viewRef.current?.dispatch({
      effects: configuration.reconfigure(configuredExtensions),
    });
  }, [configuration, configuredExtensions, document]);

  useLayoutEffect(() => {
    if (!editable) document.closeHistoryGroup();
  }, [document, editable]);

  useEffect(() => {
    const mounted = mountedRef.current;
    mountedRef.current = true;
    if (!active) return;
    const parent = parentRef.current;
    const group = parent?.closest("[data-editor-group]");
    if (mounted && group?.contains(parent!.ownerDocument.activeElement)) return;
    viewRef.current?.focus();
  }, [active, document, viewId]);

  return <div ref={parentRef} className="cm-theme-none h-full min-h-0 w-full min-w-0" />;
}

function createEditorTheme(
  EditorView: typeof import("@codemirror/view").EditorView,
  themeMode: "light" | "dark",
) {
  // Gutter text is smaller than code, so it needs the code's line box spelled out to stay aligned.
  const lineBox = "calc(var(--editor-font-size) * var(--editor-line-height))";
  return EditorView.theme({
    "&": {
      backgroundColor: "var(--editor-bg)",
      color: "var(--editor-text)",
      fontFamily: "var(--editor-font-family)",
      fontSize: "var(--editor-font-size)",
      lineHeight: "var(--editor-line-height)",
      // Coding fonts would otherwise merge != and >= into single glyphs.
      fontVariantLigatures: "none",
      fontFeatureSettings: '"liga" 0, "calt" 0',
    },
    ".cm-scroller": {
      fontFamily: "var(--editor-font-family)",
      fontSize: "var(--editor-font-size)",
      lineHeight: "var(--editor-line-height)",
    },
    ".cm-content": {
      caretColor: "var(--editor-cursor)",
      fontFamily: "var(--editor-font-family)",
      fontSize: "var(--editor-font-size)",
      lineHeight: "var(--editor-line-height)",
    },
    ".cm-gutters": {
      // Opaque, so horizontally scrolled code does not show through the line numbers.
      backgroundColor: "var(--editor-bg)",
      color: "var(--editor-gutter-text)",
      border: "none",
      fontFamily: "var(--editor-font-family)",
      fontSize: "var(--editor-gutter-font-size)",
      lineHeight: lineBox,
    },
    ".cm-lineNumbers .cm-gutterElement": {
      padding: "0 3px 0 12px",
    },
    ".cm-foldGutter .cm-gutterElement": {
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      width: "16px",
      cursor: "pointer",
    },
    ".cm-fold-marker": {
      display: "block",
      width: "6px",
      height: "6px",
      marginTop: "-3px",
      borderRight: "1.5px solid currentColor",
      borderBottom: "1.5px solid currentColor",
      transform: "rotate(45deg)",
      opacity: "0",
      transition: "opacity 120ms ease",
    },
    ".cm-fold-marker-closed": {
      marginTop: "0",
      marginLeft: "-3px",
      transform: "rotate(-45deg)",
      opacity: "1",
    },
    ".cm-gutters:hover .cm-fold-marker": {
      opacity: "1",
    },
    "@media (hover: none)": {
      ".cm-fold-marker": {
        opacity: "1",
      },
    },
    ".cm-foldPlaceholder": {
      backgroundColor: "var(--editor-active-line-bg)",
      border: "1px solid var(--border)",
      color: "var(--editor-gutter-text)",
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
    ".cm-selectionMatch": {
      backgroundColor: "var(--editor-search-bg)",
    },
    "&.cm-focused .cm-matchingBracket": {
      backgroundColor: "var(--editor-selection-bg)",
      outline: "1px solid var(--editor-search-border)",
    },
    ".cm-cursor, .cm-dropCursor": {
      borderLeftColor: "var(--editor-cursor)",
    },
    ".cm-searchMatch, .cm-searchMatch-selected": {
      backgroundColor: "var(--editor-search-bg)",
    },
    ".cm-searchMatch-selected": {
      outline: "1px solid var(--editor-search-border)",
    },
    ".cm-panels": {
      backgroundColor: "var(--editor-completion-bg)",
      color: "var(--editor-completion-text)",
    },
    ".cm-panels.cm-panels-top": { borderBottom: "1px solid var(--border)" },
    ".cm-panels.cm-panels-bottom": { borderTop: "1px solid var(--border)" },
    ".cm-textfield": {
      backgroundColor: "transparent",
      border: "1px solid var(--border)",
      borderRadius: "4px",
      color: "inherit",
    },
    ".cm-button": {
      backgroundImage: "none",
      backgroundColor: "var(--editor-active-line-bg)",
      border: "1px solid var(--border)",
      borderRadius: "4px",
      color: "inherit",
    },
    ".cm-tooltip, .cm-tooltip.cm-tooltip-autocomplete, .cm-tooltip.cm-completionInfo": {
      backgroundColor: "var(--editor-completion-bg)",
      color: "var(--editor-completion-text)",
      borderColor: "var(--border)",
    },
    ".cm-tooltip-autocomplete ul li[aria-selected]": {
      backgroundColor: "var(--editor-completion-selected-bg)",
      color: "var(--editor-completion-text)",
    },
    ".cm-tooltip-autocomplete ul": {
      fontFamily: "var(--editor-font-family)",
      fontVariantLigatures: "none",
    },
    ".cm-completionDetail": {
      color: "var(--editor-gutter-text)",
      fontStyle: "normal",
    },
    ".cm-diagnostic": {
      whiteSpace: "pre-wrap",
      overflowWrap: "anywhere",
    },
    ".cm-diagnostic-error": { borderLeftColor: "var(--editor-diagnostic-error)" },
    ".cm-diagnostic-warning": { borderLeftColor: "var(--editor-diagnostic-warning)" },
    ".cm-diagnostic-info, .cm-diagnostic-hint": { borderLeftColor: "var(--editor-diagnostic-info)" },
    ".cm-lintRange-error": {
      backgroundImage: "none",
      textDecoration: "underline wavy var(--editor-diagnostic-error)",
    },
    ".cm-lintRange-warning": {
      backgroundImage: "none",
      textDecoration: "underline wavy var(--editor-diagnostic-warning)",
    },
    ".cm-lintRange-info, .cm-lintRange-hint": {
      backgroundImage: "none",
      textDecoration: "underline wavy var(--editor-diagnostic-info)",
    },
    ".cm-lintPoint:after": { borderBottomColor: "var(--editor-diagnostic-error)" },
    ".cm-lintPoint-warning:after": { borderBottomColor: "var(--editor-diagnostic-warning)" },
    ".cm-lintPoint-info:after, .cm-lintPoint-hint:after": { borderBottomColor: "var(--editor-diagnostic-info)" },
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
        backgroundColor: "var(--editor-breakpoint)",
        boxShadow: "0 0 0 1px var(--editor-breakpoint-border)",
      },
      ".cm-debug-current-line": {
        backgroundColor: "var(--editor-active-line-bg)",
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

function resolveTextareaNavigationTarget(
  path: string,
  value: string,
  offset: number,
  kind: CodeNavigationIntentKind,
) {
  const boundedOffset = Math.min(Math.max(offset, 0), value.length);
  const before = value.slice(0, boundedOffset);
  const line = before.split(/\r?\n/).length;
  const lineStart = before.lastIndexOf("\n") + 1;
  const utf16ColumnOffset = boundedOffset - lineStart;
  const column = Array.from(value.slice(lineStart, boundedOffset)).length + 1;
  const lineEnd = value.indexOf("\n", boundedOffset);
  const currentLineText = value.slice(lineStart, lineEnd === -1 ? value.length : lineEnd);
  const symbol = extractFileEditorSymbolAt(currentLineText, Math.max(0, utf16ColumnOffset));
  return {
    kind,
    path,
    line,
    column,
    ...(symbol ? { symbol } : {}),
  };
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
  sessionKey,
  viewId = "main",
  active = true,
  documentPaths,
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
  canFindReferences = false,
  statusText = "",
  error = "",
  hideHeader = false,
  inlineCompletion,
  codeNavigationHover,
  languageFeatures,
  onToggleBreakpoint,
  onResolveCodeNavigation,
  onCursorChange,
  onChange,
  onSave,
  onClose,
}: Props) {
  const appearance = useResolvedAppearance();
  const [editorRuntime, setEditorRuntime] = useState<EditorRuntime | null>(null);
  const [editorView, setEditorView] = useState<CodeMirrorEditorView | null>(null);
  const [navigationMenuOpen, setNavigationMenuOpen] = useState(false);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; hasSelection: boolean } | null>(null);
  const contextMenuRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const handledRevealRef = useRef<{ requestId: string; target: object } | null>(null);
  const handledNavigationRef = useRef<string | null>(null);
  const codeNavigationHoverRef = useRef(codeNavigationHover);
  const languageFeaturesRef = useRef(languageFeatures);
  const onCursorChangeRef = useRef(onCursorChange);
  const canUseCodeMirror = typeof window !== "undefined" && typeof window.ResizeObserver !== "undefined";
  // Color variables follow the snapshot on the root; only scheme changes need reconfiguration.
  const editorTheme = useMemo(() => createEditorTheme(codemirrorView.EditorView, appearance.scheme), [appearance.scheme]);
  const normalizedBreakpointLines = breakpointLines ?? EMPTY_BREAKPOINT_LINES;
  const canShowCodeNavigationHover = Boolean(onResolveCodeNavigation && codeNavigationHover);
  const codeNavigationHoverContextKey = codeNavigationHover?.contextKey ?? codeNavigationHover;

  useLayoutEffect(() => {
    codeNavigationHoverRef.current = codeNavigationHover;
  }, [codeNavigationHover]);

  useLayoutEffect(() => {
    languageFeaturesRef.current = languageFeatures;
    onCursorChangeRef.current = onCursorChange;
  }, [languageFeatures, onCursorChange]);

  // The editor always holds LF text; the owner may still hold the file's CRLF text.
  const editorValue = useMemo(() => (value.includes("\r") ? value.replace(/\r\n?/g, "\n") : value), [value]);
  const editorValueRef = useRef(editorValue);
  useLayoutEffect(() => {
    editorValueRef.current = editorValue;
  }, [editorValue]);

  useEffect(() => {
    if (sessionKey && documentPaths) pruneFileEditorDocuments(sessionKey, documentPaths);
  }, [documentPaths, sessionKey]);

  const codeNavigationHoverExtensions = useMemo(() => {
    if (!canShowCodeNavigationHover) {
      return [];
    }
    return createFileEditorCodeNavigationHover({
      path,
      hoverDelayMs: codeNavigationHover?.hoverDelayMs,
      request: (input, signal) => (
        codeNavigationHoverRef.current?.request(input, signal) ?? Promise.resolve(false)
      ),
    });
  }, [canShowCodeNavigationHover, codeNavigationHover?.hoverDelayMs, codeNavigationHoverContextKey, path]);

  const hasLanguageFeatures = Boolean(languageFeatures);
  const languageHover = Boolean(languageFeatures?.hover);
  const languageSemanticTokens = Boolean(languageFeatures?.semanticTokens);
  const languageDiagnostics = Boolean(languageFeatures?.diagnostics);
  const languageCompletion = Boolean(languageFeatures?.completion);
  // Requests go through the ref, so content edits never reconfigure the editor.
  const languageFeatureExtensions = useMemo(() => {
    if (!hasLanguageFeatures) {
      return [];
    }
    return createFileEditorLanguageFeatures({
      hover: languageHover,
      semanticTokens: languageSemanticTokens,
      diagnostics: languageDiagnostics,
      completion: languageCompletion,
      request: async (query, content, signal) => {
        // An edit reaches the owner's state a render later; never pair new positions with old text.
        for (let attempt = 0; editorValueRef.current !== content; attempt += 1) {
          if (attempt >= LANGUAGE_FEATURE_SYNC_ATTEMPTS || signal.aborted) {
            return null;
          }
          await new Promise<void>((resolve) => {
            window.setTimeout(resolve, LANGUAGE_FEATURE_SYNC_INTERVAL_MS);
          });
        }
        if (signal.aborted) {
          return null;
        }
        return languageFeaturesRef.current?.request(query, signal) ?? null;
      },
    });
  }, [hasLanguageFeatures, languageCompletion, languageDiagnostics, languageHover, languageSemanticTokens, path]);

  const cursorListenerExtension = useMemo(() => codemirrorView.EditorView.updateListener.of((update) => {
    if (update.selectionSet || update.docChanged) {
      onCursorChangeRef.current?.(offsetToCodePosition(update.state.doc, update.state.selection.main.head));
    }
  }), []);

  // Detected once per opened file: retyping must not flip the indentation unit mid-edit.
  const indentGuideExtensions = useMemo(
    () => createFileEditorIndentGuides(loading ? null : codemirrorState.Text.of(value.split(/\r?\n/))),
    [loading, path],
  );
  const stickyScrollExtensions = useMemo(() => createFileEditorStickyScroll(), []);
  const nameConventionExtensions = useMemo(
    () => createFileEditorNameConventions(inferFileEditorLanguageId(path)),
    [path],
  );

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
          getDefaultExtensions: module.getDefaultExtensions,
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
      FILE_EDITOR_FOLD_GUTTER,
      FILE_EDITOR_OCCURRENCES,
      ...indentGuideExtensions,
      ...stickyScrollExtensions,
      cursorListenerExtension,
      ...createDebugExtensions(
        editorRuntime.viewModule,
        editorRuntime.stateModule,
        normalizedBreakpointLines,
        currentLine,
        onToggleBreakpoint,
      ),
      editorTheme,
    ];
    if (inlineCompletion) {
      extensions.push(...createFileEditorInlineCompletion(inlineCompletion));
    }
    // Semantic tokens come first so they outrank the convention-based guesses.
    extensions.push(...codeNavigationHoverExtensions, ...languageFeatureExtensions, ...nameConventionExtensions);
    return extensions;
  }, [
    editorTheme,
    codeNavigationHoverExtensions,
    currentLine,
    cursorListenerExtension,
    editorRuntime,
    indentGuideExtensions,
    inlineCompletion,
    languageFeatureExtensions,
    nameConventionExtensions,
    normalizedBreakpointLines,
    onToggleBreakpoint,
    stickyScrollExtensions,
  ]);

  const CodeMirrorEditor = editorRuntime?.CodeMirrorEditor ?? null;

  useEffect(() => {
    setNavigationMenuOpen(false);
    setContextMenu(null);
  }, [path]);

  useEffect(() => {
    if (editorView) {
      onCursorChangeRef.current?.(offsetToCodePosition(editorView.state.doc, editorView.state.selection.main.head));
    }
  }, [editorView]);

  const languageFeatureRefreshKey = languageFeatures?.refreshKey;
  const renderedLanguageFeatureRefreshKeyRef = useRef(languageFeatureRefreshKey);
  useEffect(() => {
    if (renderedLanguageFeatureRefreshKeyRef.current === languageFeatureRefreshKey) {
      return;
    }
    renderedLanguageFeatureRefreshKeyRef.current = languageFeatureRefreshKey;
    if (editorView && hasLanguageFeatures) {
      editorView.dispatch({ effects: refreshFileEditorLanguageFeatures.of(null) });
    }
  }, [editorView, hasLanguageFeatures, languageFeatureRefreshKey]);

  useLayoutEffect(() => {
    if (!contextMenu || !contextMenuRef.current) {
      return;
    }
    const bounds = contextMenuRef.current.getBoundingClientRect();
    const x = Math.max(8, Math.min(contextMenu.x, window.innerWidth - bounds.width - 8));
    const y = Math.max(8, Math.min(contextMenu.y, window.innerHeight - bounds.height - 8));
    if (x !== contextMenu.x || y !== contextMenu.y) {
      setContextMenu({ ...contextMenu, x, y });
    }
  }, [contextMenu]);

  useEffect(() => {
    if (!contextMenu) {
      return undefined;
    }
    const close = () => setContextMenu(null);
    const closeOnPointerDown = (event: PointerEvent) => {
      if (!contextMenuRef.current?.contains(event.target as Node)) close();
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      close();
      editorView?.focus();
    };
    document.addEventListener("pointerdown", closeOnPointerDown, true);
    document.addEventListener("keydown", closeOnEscape);
    window.addEventListener("blur", close);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("pointerdown", closeOnPointerDown, true);
      document.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("blur", close);
      window.removeEventListener("resize", close);
    };
  }, [contextMenu, editorView]);

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
    if (!active || !reveal) {
      return;
    }
    const target = editorView ?? textareaRef.current;
    if (handledRevealRef.current?.requestId === reveal.requestId && handledRevealRef.current.target === target) {
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
      handledRevealRef.current = { requestId: reveal.requestId, target: editorView };
      return;
    }

    const textarea = textareaRef.current;
    const position = textOffsetAtPosition(value, reveal.line, reveal.column);
    if (!textarea || position === null) {
      return;
    }
    textarea.setSelectionRange(position, position);
    textarea.focus();
    handledRevealRef.current = { requestId: reveal.requestId, target: textarea };
    const lineHeight = Number.parseFloat(window.getComputedStyle(textarea).lineHeight) || 20;
    textarea.scrollTop = Math.max(0, (reveal.line - 1) * lineHeight - textarea.clientHeight / 2);
  }, [active, editorView, reveal?.requestId]);

  function requestCodeNavigation(kind: CodeNavigationIntentKind) {
    if (
      !active
      || !onResolveCodeNavigation
      || (kind === "implementation" && !canNavigateImplementation)
      || (kind === "references" && !canFindReferences)
    ) {
      return false;
    }
    const target = editorView
      ? resolveFileEditorNavigationTargetAtPosition(editorView, path, editorView.state.selection.main.head, kind)
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
    if (event.key !== "F12" || event.altKey || (event.shiftKey && (event.ctrlKey || event.metaKey))) {
      return;
    }
    const kind = event.shiftKey
      ? "references"
      : event.ctrlKey || event.metaKey ? "implementation" : "definition";
    if (requestCodeNavigation(kind)) {
      event.preventDefault();
    }
  }

  async function runClipboardAction(action: "cut" | "copy" | "paste" | "selectAll") {
    setContextMenu(null);
    if (!editorView) {
      return;
    }
    editorView.focus();
    const { state } = editorView;
    if (action === "selectAll") {
      editorView.dispatch({ selection: { anchor: 0, head: state.doc.length } });
      return;
    }
    const editable = !state.readOnly && state.facet(codemirrorView.EditorView.editable);
    try {
      if (action === "paste") {
        if (!editable) return;
        const text = await navigator.clipboard.readText();
        if (text) editorView.dispatch(editorView.state.replaceSelection(text), { userEvent: "input.paste" });
        return;
      }
      const ranges = state.selection.ranges.filter((range) => !range.empty);
      if (ranges.length === 0) return;
      await navigator.clipboard.writeText(ranges.map((range) => state.sliceDoc(range.from, range.to)).join(state.lineBreak));
      if (action === "cut" && editable) {
        editorView.dispatch({
          changes: ranges.map((range) => ({ from: range.from, to: range.to })),
          userEvent: "delete.cut",
        });
      }
    } catch {
      // Browsers may withhold clipboard access; the keyboard shortcuts keep working.
    }
  }

  useEffect(() => {
    if (active && navigationCommand && handledNavigationRef.current !== navigationCommand.requestId) {
      handledNavigationRef.current = navigationCommand.requestId;
      requestCodeNavigation(navigationCommand.kind);
    }
  }, [active, navigationCommand?.requestId]);

  function saveDocument() {
    if (sessionKey) getFileEditorDocument(sessionKey, path, value).closeHistoryGroup();
    onSave();
  }

  useEffect(() => {
    if (!active || !canSave || loading || saving || typeof window === "undefined") {
      return undefined;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        saveDocument();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [active, canSave, loading, onSave, path, saving, sessionKey, value]);
  return (
    <section className="file-editor-container flex h-full min-h-0 flex-1 flex-col overflow-hidden bg-transparent">
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
                onClick={saveDocument}
                disabled={loading || saving || !canSave}
                className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm text-[var(--accent-foreground)] disabled:opacity-60"
              >
                {saving ? "保存中..." : "保存"}
              </button>
            </div>
          </div>
          {statusText ? <p className="mt-2 text-sm text-[var(--muted)]">{statusText}</p> : null}
          {error ? <p className="mt-2 text-sm text-[var(--status-danger)]">{error}</p> : null}
        </div>
      ) : null}
      <div className="relative min-h-0 flex-1 overflow-hidden">
        {CodeMirrorEditor ? (
          <div
            key={path}
            data-testid="file-editor-host"
            className="file-editor-surface flex h-full min-h-0 min-w-0 overflow-hidden bg-[var(--editor-bg)] text-[var(--editor-text)]"
            onKeyDown={handleCodeNavigationKeyDown}
            onContextMenu={(event) => {
              // Shift keeps the browser's own menu reachable.
              if (!active || !editorView || event.shiftKey) {
                return;
              }
              const target = event.target;
              if (target instanceof HTMLElement && target.closest(".cm-gutters, .cm-panels, .cm-sticky-scroll")) {
                return;
              }
              event.preventDefault();
              const position = editorView.posAtCoords({ x: event.clientX, y: event.clientY });
              const { main } = editorView.state.selection;
              // Like desktop editors: a right-click outside the selection moves the cursor there.
              if (position !== null && (main.empty || position < main.from || position > main.to)) {
                editorView.dispatch({ selection: { anchor: position } });
              }
              setContextMenu({
                x: event.clientX,
                y: event.clientY,
                hasSelection: editorView.state.selection.ranges.some((range) => !range.empty),
              });
            }}
            onMouseDown={(event) => {
              if (!active || !onResolveCodeNavigation || !editorView || event.button !== 0 || (!event.ctrlKey && !event.metaKey)) {
                return;
              }
              const target = event.target;
              if (target instanceof HTMLElement && target.closest(".cm-gutters")) {
                return;
              }
              const definitionTarget = resolveFileEditorNavigationTargetAtCoordinates(
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
            {sessionKey ? (
              <SharedFileEditor
                sessionKey={sessionKey}
                path={path}
                viewId={viewId}
                value={value}
                active={active}
                editable={!loading && !saving && !readOnly}
                readOnly={readOnly}
                runtime={editorRuntime!}
                extensions={editorExtensions}
                onCreateEditor={setEditorView}
                onChange={onChange}
              />
            ) : <CodeMirrorEditor
              key={path}
              value={value}
              className="h-full min-h-0 w-full min-w-0"
              height="100%"
              width="100%"
              theme="none"
              extensions={editorExtensions}
              autoFocus={active}
              editable={!loading && !saving && !readOnly}
              onCreateEditor={(view) => {
                setEditorView(view);
              }}
              basicSetup={FILE_EDITOR_BASIC_SETUP}
              onChange={onChange}
            />}
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
              if (!active || !onResolveCodeNavigation || event.button !== 0 || (!event.ctrlKey && !event.metaKey)) {
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
            className="block h-full min-h-0 w-full resize-none overflow-auto border-0 bg-transparent p-4 text-[var(--editor-text)] outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent)]"
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
              className="inline-flex h-9 w-9 touch-manipulation items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--surface)] text-[var(--muted)] shadow-[var(--shadow-float)]"
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
                {canFindReferences ? (
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setNavigationMenuOpen(false);
                      requestCodeNavigation("references");
                    }}
                    className="flex w-full touch-manipulation rounded-md px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                  >
                    查找所有引用
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
      {/* Portalled: the glass editor pane would otherwise be the containing block of this fixed menu. */}
      {contextMenu && typeof document !== "undefined" ? createPortal(
        <div
          ref={contextMenuRef}
          role="menu"
          aria-label="编辑器菜单"
          data-testid="file-editor-context-menu"
          className="desktop-workbench-menu fixed z-40 w-52 rounded-md border border-[var(--border)] bg-[var(--surface)] p-1 text-[var(--text)] shadow-[var(--shadow-card)]"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onContextMenu={(event) => {
            event.preventDefault();
            event.stopPropagation();
          }}
        >
          {onResolveCodeNavigation ? (
            <>
              {([
                { kind: "definition", label: "转到定义", shortcut: "F12", enabled: true },
                { kind: "implementation", label: "转到实现", shortcut: "Ctrl+F12", enabled: canNavigateImplementation },
                { kind: "references", label: "查找所有引用", shortcut: "Shift+F12", enabled: canFindReferences },
              ] as const).map((item) => (
                <button
                  key={item.kind}
                  type="button"
                  role="menuitem"
                  disabled={!item.enabled}
                  onClick={() => {
                    setContextMenu(null);
                    requestCodeNavigation(item.kind);
                  }}
                  className="flex w-full items-center justify-between gap-4 rounded-md px-3 py-1.5 text-left text-sm hover:bg-[var(--surface-strong)] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <span>{item.label}</span>
                  <span className="text-xs text-[var(--muted)]">{item.shortcut}</span>
                </button>
              ))}
              <div role="separator" className="my-1 border-t border-[var(--border)]" />
            </>
          ) : null}
          {([
            { action: "cut", label: "剪切", shortcut: "Ctrl+X", enabled: contextMenu.hasSelection && !readOnly },
            { action: "copy", label: "复制", shortcut: "Ctrl+C", enabled: contextMenu.hasSelection },
            { action: "paste", label: "粘贴", shortcut: "Ctrl+V", enabled: !readOnly },
            { action: "selectAll", label: "全选", shortcut: "Ctrl+A", enabled: true },
          ] as const).map((item) => (
            <button
              key={item.action}
              type="button"
              role="menuitem"
              disabled={!item.enabled}
              onClick={() => {
                void runClipboardAction(item.action);
              }}
              className="flex w-full items-center justify-between gap-4 rounded-md px-3 py-1.5 text-left text-sm hover:bg-[var(--surface-strong)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              <span>{item.label}</span>
              <span className="text-xs text-[var(--muted)]">{item.shortcut}</span>
            </button>
          ))}
        </div>,
        document.body,
      ) : null}
    </section>
  );
}
