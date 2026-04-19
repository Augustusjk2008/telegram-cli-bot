import { type ComponentType, useEffect, useRef, useState } from "react";
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
  extensions?: unknown[];
  autoFocus?: boolean;
  editable?: boolean;
  basicSetup?: unknown;
  onChange?: (value: string) => void;
}>;

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
  const editorHostRef = useRef<HTMLDivElement | null>(null);
  const canUseCodeMirror = typeof window !== "undefined" && typeof window.ResizeObserver !== "undefined";

  useEffect(() => {
    let active = true;
    if (!canUseCodeMirror) {
      setCodeMirrorEditor(null);
      setEditorExtensions([]);
      return () => {
        active = false;
      };
    }

    void Promise.all([import("@uiw/react-codemirror"), loadFileEditorExtensions(path)])
      .then(([module, loadedExtensions]) => {
        if (!active) {
          return;
        }
        setCodeMirrorEditor(() => module.default as CodeMirrorComponent);
        setEditorExtensions(loadedExtensions);
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
  }, [canUseCodeMirror, path]);

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

  useEffect(() => {
    const host = editorHostRef.current;
    if (!host) {
      return;
    }

    const wrapper = host.firstElementChild instanceof HTMLElement ? host.firstElementChild : null;
    const editor = host.querySelector<HTMLElement>(".cm-editor");
    const scroller = host.querySelector<HTMLElement>(".cm-scroller");
    const gutters = host.querySelector<HTMLElement>(".cm-gutters");
    const content = host.querySelector<HTMLElement>(".cm-content");
    if (wrapper) {
      wrapper.style.height = "100%";
      wrapper.style.width = "100%";
      wrapper.style.minHeight = "0";
      wrapper.style.minWidth = "0";
      wrapper.style.display = "flex";
      wrapper.style.overflow = "hidden";
    }
    if (editor) {
      editor.style.height = "100%";
      editor.style.minHeight = "0";
      editor.style.width = "100%";
      editor.style.minWidth = "0";
      editor.style.display = "flex";
      editor.style.flex = "1 1 auto";
      editor.style.flexDirection = "column";
      editor.style.overflow = "hidden";
    }
    if (gutters) {
      gutters.style.flexShrink = "0";
    }
    if (content) {
      content.style.minWidth = "100%";
    }
    if (!scroller) {
      return;
    }

    scroller.style.flex = "1 1 auto";
    scroller.style.minHeight = "0";
    scroller.style.minWidth = "0";
    scroller.style.width = "100%";
    scroller.style.height = "auto";
    scroller.style.maxHeight = "none";
    scroller.style.overflow = "auto";
    scroller.style.touchAction = "pan-x pan-y";
    scroller.style.overscrollBehavior = "contain";
    scroller.style.scrollbarGutter = "stable both-edges";
    (scroller.style as CSSStyleDeclaration & { webkitOverflowScrolling?: string }).webkitOverflowScrolling = "touch";
  }, [CodeMirrorEditor, path]);

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
            ref={editorHostRef}
            data-testid="file-editor-host"
            className="flex h-full min-h-0 min-w-0 overflow-hidden bg-[var(--bg)]"
          >
            <CodeMirrorEditor
              value={value}
              className="h-full min-h-0 w-full min-w-0"
              height="100%"
              width="100%"
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
            className="block h-full min-h-0 w-full resize-none overflow-auto border-0 bg-[var(--bg)] p-4 font-mono text-sm text-[var(--text)] outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent)]"
          />
        )}
      </div>
    </section>
  );
}
