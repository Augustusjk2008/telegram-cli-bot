import { type ComponentType, useEffect, useState } from "react";
import { loadFileEditorExtensions } from "../utils/fileEditorLanguage";

type Props = {
  path: string;
  value: string;
  loading?: boolean;
  saving?: boolean;
  dirty?: boolean;
  canSave?: boolean;
  statusText?: string;
  error?: string;
  hideHeader?: boolean;
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
  onChange?: (value: string) => void;
}>;

function createEditorTheme(
  EditorView: typeof import("@codemirror/view").EditorView,
  themeMode: "light" | "dark",
) {
  return EditorView.theme({
    "&": {
      backgroundColor: "var(--editor-bg)",
      color: "var(--editor-text)",
    },
    ".cm-content": {
      caretColor: "var(--editor-text)",
    },
    ".cm-gutters": {
      backgroundColor: "var(--editor-gutter-bg)",
      color: "var(--editor-gutter-text)",
      borderRight: "1px solid var(--border)",
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

export function FileEditorSurface({
  path,
  value,
  loading = false,
  saving = false,
  dirty = false,
  canSave = false,
  statusText = "",
  error = "",
  hideHeader = false,
  onChange,
  onSave,
  onClose,
}: Props) {
  const [CodeMirrorEditor, setCodeMirrorEditor] = useState<CodeMirrorComponent | null>(null);
  const [editorExtensions, setEditorExtensions] = useState<unknown[]>([]);
  const canUseCodeMirror = typeof window !== "undefined" && typeof window.ResizeObserver !== "undefined";
  const codeMirrorTheme = typeof document !== "undefined" && document.documentElement.dataset.theme === "classic"
    ? "light"
    : "dark";

  useEffect(() => {
    let active = true;
    if (!canUseCodeMirror) {
      setCodeMirrorEditor(null);
      setEditorExtensions([]);
      return () => {
        active = false;
      };
    }

    void Promise.all([
      import("@uiw/react-codemirror"),
      loadFileEditorExtensions(path),
      import("@codemirror/view"),
    ])
      .then(([module, loadedExtensions, viewModule]) => {
        if (!active) {
          return;
        }
        setCodeMirrorEditor(() => module.default as CodeMirrorComponent);
        setEditorExtensions([...loadedExtensions, createEditorTheme(viewModule.EditorView, codeMirrorTheme)]);
      })
      .catch(() => {
        if (!active) {
          return;
        }
        setCodeMirrorEditor(null);
        setEditorExtensions([]);
      });

    return () => {
      active = false;
    };
  }, [canUseCodeMirror, codeMirrorTheme, path]);

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
              basicSetup={{
                lineNumbers: true,
                foldGutter: true,
                highlightActiveLineGutter: true,
              }}
              onChange={onChange}
            />
          </div>
        ) : (
          <textarea
            key={path}
            aria-label="文件内容"
            value={value}
            onChange={(event) => onChange(event.target.value)}
            spellCheck={false}
            style={{
              touchAction: "pan-x pan-y",
              overscrollBehavior: "contain",
              scrollbarGutter: "stable both-edges",
              WebkitOverflowScrolling: "touch",
            }}
            className="block h-full min-h-0 w-full resize-none overflow-auto border-0 bg-[var(--editor-bg)] p-4 font-mono text-sm text-[var(--editor-text)] outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent)]"
          />
        )}
      </div>
    </section>
  );
}
