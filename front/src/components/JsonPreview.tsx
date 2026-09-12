import { json } from "@codemirror/lang-json";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorView } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import CodeMirror from "@uiw/react-codemirror";
import { clsx } from "clsx";
import { useMemo } from "react";
import { formatJsonPreview } from "../utils/jsonPreview";

type Props = {
  content: string;
  isFullContent: boolean;
  desktop?: boolean;
};

const JSON_PREVIEW_EXTENSIONS = [
  json(),
  syntaxHighlighting(HighlightStyle.define([
    { tag: tags.propertyName, color: "var(--editor-syntax-function)" },
    { tag: tags.string, color: "var(--editor-syntax-string)" },
    { tag: tags.number, color: "var(--editor-syntax-number)" },
    { tag: tags.bool, color: "var(--editor-syntax-keyword)" },
    { tag: tags.null, color: "var(--editor-syntax-meta)" },
  ])),
  EditorView.contentAttributes.of({ "aria-label": "JSON 内容", "aria-readonly": "true", tabindex: "0" }),
  EditorView.theme({
    "&": {
      flex: "1",
      minHeight: "0",
      backgroundColor: "var(--editor-bg)",
      color: "var(--editor-text)",
      fontSize: "var(--editor-font-size)",
      lineHeight: "var(--editor-line-height)",
    },
    "&.cm-focused": { outline: "none" },
    ".cm-scroller": { overflow: "auto", fontFamily: "var(--editor-font-family)" },
    ".cm-content": { padding: "12px 0", userSelect: "text" },
    ".cm-gutters": {
      backgroundColor: "var(--editor-gutter-bg)",
      color: "var(--editor-gutter-text)",
      borderRight: "1px solid var(--border)",
    },
    ".cm-selectionBackground, &.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground": {
      backgroundColor: "var(--editor-selection-bg)",
    },
    ".cm-content ::selection, .cm-content::selection": { backgroundColor: "var(--editor-selection-bg)" },
  }),
];

const JSON_PREVIEW_BASIC_SETUP = {
  lineNumbers: true,
  foldGutter: false,
  highlightActiveLine: false,
  highlightActiveLineGutter: false,
  highlightSelectionMatches: false,
  autocompletion: false,
  history: false,
};

const STATUS_MESSAGES = {
  formatted: "",
  incomplete: "内容未完整读取，暂无法格式化",
  empty: "文件为空",
  invalid: "JSON 格式错误",
  "too-large": "格式化结果超过 4 MiB，已显示原文",
};

export function JsonPreview({ content, isFullContent, desktop = false }: Props) {
  const result = useMemo(() => formatJsonPreview(content, isFullContent), [content, isFullContent]);
  const message = STATUS_MESSAGES[result.status];

  return (
    <div className={clsx("flex min-h-0 min-w-0 flex-col overflow-hidden rounded-xl bg-[var(--editor-bg)] text-[var(--editor-text)]", desktop ? "h-full" : "max-h-[50vh]")}>
      {message ? (
        <p role="status" className="shrink-0 px-4 py-3 text-sm text-[var(--muted)]">{message}</p>
      ) : null}
      {result.status !== "empty" ? (
        <CodeMirror
          value={result.content}
          className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden"
          theme="none"
          extensions={JSON_PREVIEW_EXTENSIONS}
          basicSetup={JSON_PREVIEW_BASIC_SETUP}
          readOnly
          editable={false}
          indentWithTab={false}
        />
      ) : null}
    </div>
  );
}
