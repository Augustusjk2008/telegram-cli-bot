import { foldNodeProp, syntaxTree } from "@codemirror/language";
import type { EditorState, Extension } from "@codemirror/state";
import { EditorView, ViewPlugin, type ViewUpdate } from "@codemirror/view";
import { highlightTree } from "@lezer/highlight";
import { FILE_EDITOR_HIGHLIGHT_STYLE } from "./fileEditorHighlight";

const MAX_STICKY_ROWS = 5;
const MAX_STICKY_ROWS_NARROW = 3;
const NARROW_EDITOR_WIDTH = 640;
const MAX_STICKY_TEXT_LENGTH = 400;

export type FileEditorScope = {
  /** Line that introduces the scope, shown while the scope's body is at the top of the viewport. */
  headerLine: number;
  endLine: number;
};

/**
 * Foldable scopes around a line, outermost first. Only scopes that open on an
 * earlier line count, so a block's own header line is not inside it.
 */
export function resolveFileEditorScopeChain(state: EditorState, lineNumber: number): FileEditorScope[] {
  if (lineNumber < 1 || lineNumber > state.doc.lines) return [];
  const line = state.doc.line(lineNumber);
  const indent = line.text.search(/\S/);
  const scopes: FileEditorScope[] = [];
  const seen = new Set<number>();
  for (
    let node: ReturnType<ReturnType<typeof syntaxTree>["resolveInner"]> | null
      = syntaxTree(state).resolveInner(line.from + Math.max(0, indent), 1);
    node;
    node = node.parent
  ) {
    if (!node.type.prop(foldNodeProp) || /Comment|String/.test(node.type.name)) continue;
    const startLine = state.doc.lineAt(node.from);
    if (startLine.number >= lineNumber) continue;
    // Indentation-based grammars end a block at the next statement; blank lines before it are outside.
    let end = state.doc.lineAt(node.to);
    if (end.from === node.to && end.number > startLine.number) end = state.doc.line(end.number - 1);
    while (end.number > startLine.number && !end.text.trim()) end = state.doc.line(end.number - 1);
    const endLine = end.number;
    if (endLine < lineNumber) continue;
    // An opening brace on its own line is not a useful header; show the statement that owns it.
    const owner = node.parent;
    const header = /^\s*[{[(]\s*$/.test(startLine.text) && owner?.parent
      ? state.doc.lineAt(owner.from)
      : startLine;
    if (seen.has(header.number)) continue;
    seen.add(header.number);
    scopes.push({ headerLine: header.number, endLine });
  }
  return scopes.reverse();
}

type StickyMeasure = {
  lines: number[];
  top: number;
  right: number;
  gutterWidth: number;
  numberWidth: number;
  scrollLeft: number;
  lineHeight: number;
};

function renderLineText(state: EditorState, lineNumber: number, target: HTMLElement) {
  const line = state.doc.line(lineNumber);
  const end = Math.min(line.to, line.from + MAX_STICKY_TEXT_LENGTH);
  let position = line.from;
  highlightTree(syntaxTree(state), FILE_EDITOR_HIGHLIGHT_STYLE, (from, to, classes) => {
    const start = Math.max(from, position);
    const stop = Math.min(to, end);
    if (stop <= start) return;
    if (start > position) target.append(state.doc.sliceString(position, start));
    const span = document.createElement("span");
    span.className = classes;
    span.textContent = state.doc.sliceString(start, stop);
    target.append(span);
    position = stop;
  }, line.from, end);
  if (position < end) target.append(state.doc.sliceString(position, end));
}

class StickyScrollController {
  private readonly dom: HTMLDivElement;
  private renderedKey = "";
  private renderedState: EditorState | null = null;
  private height = 0;
  private destroyed = false;

  private readonly handleScroll = () => {
    this.schedule();
  };

  constructor(private readonly view: EditorView) {
    this.dom = document.createElement("div");
    this.dom.className = "cm-sticky-scroll";
    this.dom.setAttribute("aria-hidden", "true");
    this.dom.hidden = true;
    this.dom.addEventListener("mousedown", this.handleMouseDown);
    view.dom.appendChild(this.dom);
    view.scrollDOM.addEventListener("scroll", this.handleScroll, { passive: true });
    this.schedule();
  }

  get stickyHeight() {
    return this.height;
  }

  update(update: ViewUpdate) {
    if (
      update.docChanged
      || update.geometryChanged
      || update.viewportChanged
      || syntaxTree(update.startState) !== syntaxTree(update.state)
    ) {
      this.schedule();
    }
  }

  destroy() {
    this.destroyed = true;
    this.view.scrollDOM.removeEventListener("scroll", this.handleScroll);
    this.dom.removeEventListener("mousedown", this.handleMouseDown);
    this.dom.remove();
  }

  private readonly handleMouseDown = (event: MouseEvent) => {
    const row = (event.target as HTMLElement | null)?.closest<HTMLElement>("[data-sticky-line]");
    const lineNumber = Number(row?.dataset.stickyLine);
    if (!lineNumber || lineNumber > this.view.state.doc.lines) return;
    event.preventDefault();
    const line = this.view.state.doc.line(lineNumber);
    this.view.dispatch({
      selection: { anchor: line.from },
      effects: EditorView.scrollIntoView(line.from, { y: "start" }),
    });
    this.view.focus();
  };

  private schedule() {
    if (this.destroyed) return;
    this.view.requestMeasure({
      key: this,
      read: () => this.measure(),
      write: (measure) => this.render(measure),
    });
  }

  private measure(): StickyMeasure {
    const { view } = this;
    const scroller = view.scrollDOM;
    const scrollerRect = scroller.getBoundingClientRect();
    const editorRect = view.dom.getBoundingClientRect();
    const lineHeight = view.defaultLineHeight;
    const scaleY = view.scaleY || 1;
    const gutterWidth = view.dom.querySelector<HTMLElement>(".cm-gutters")?.offsetWidth ?? 0;
    const numbers = view.dom.querySelector<HTMLElement>(".cm-gutter.cm-lineNumbers");
    const base: StickyMeasure = {
      lines: [],
      top: (scrollerRect.top - editorRect.top) / scaleY,
      right: Math.max(0, scroller.offsetWidth - scroller.clientWidth),
      gutterWidth,
      // Other gutters (folding, breakpoints) may sit on either side of the numbers.
      numberWidth: numbers ? Math.min(gutterWidth, numbers.offsetLeft + numbers.offsetWidth) : gutterWidth,
      scrollLeft: scroller.scrollLeft,
      lineHeight,
    };
    // Sticky rows may take at most a quarter of a short editor, and fewer on phone-sized ones.
    const maxRows = Math.min(
      scroller.clientWidth < NARROW_EDITOR_WIDTH ? MAX_STICKY_ROWS_NARROW : MAX_STICKY_ROWS,
      Math.floor(scroller.clientHeight / lineHeight / 4),
    );
    if (maxRows <= 0 || scroller.scrollTop <= 0) return base;
    const viewportTop = (scrollerRect.top - view.documentTop) / scaleY;
    const chains = new Map<number, FileEditorScope[]>();
    for (let index = 0; index < maxRows; index += 1) {
      // Row `index` covers the document line lying under it.
      const rowTop = viewportTop + index * lineHeight;
      const block = view.lineBlockAtHeight(rowTop + 1);
      const lineNumber = view.state.doc.lineAt(block.from).number;
      let chain = chains.get(lineNumber);
      if (!chain) {
        chain = resolveFileEditorScopeChain(view.state, lineNumber);
        chains.set(lineNumber, chain);
      }
      const scope = chain[index];
      if (!scope) break;
      // Rows nest: a deeper row is only valid under the same outer scopes.
      if (base.lines.some((headerLine, depth) => chain![depth]?.headerLine !== headerLine)) break;
      const headerTop = view.lineBlockAt(view.state.doc.line(scope.headerLine).from).top;
      if (headerTop >= rowTop) break;
      base.lines.push(scope.headerLine);
    }
    return base;
  }

  private render(measure: StickyMeasure) {
    if (this.destroyed) return;
    const { view } = this;
    const key = [
      measure.lines.join(","),
      measure.top,
      measure.right,
      measure.gutterWidth,
      measure.numberWidth,
      measure.lineHeight,
    ].join("|");
    const height = measure.lines.length * measure.lineHeight;
    if (key !== this.renderedKey || this.renderedState !== view.state) {
      this.renderedKey = key;
      this.renderedState = view.state;
      this.dom.hidden = measure.lines.length === 0;
      this.dom.style.top = `${measure.top}px`;
      this.dom.style.right = `${measure.right}px`;
      this.dom.style.setProperty("--sticky-number-width", `${measure.numberWidth}px`);
      this.dom.style.setProperty("--sticky-gutter-rest", `${measure.gutterWidth - measure.numberWidth}px`);
      this.dom.style.setProperty("--sticky-line-height", `${measure.lineHeight}px`);
      this.dom.style.tabSize = String(view.state.tabSize);
      this.dom.replaceChildren(...measure.lines.map((lineNumber) => {
        const row = document.createElement("div");
        row.className = "cm-sticky-scroll-row";
        row.dataset.stickyLine = String(lineNumber);
        const number = document.createElement("span");
        number.className = "cm-sticky-scroll-number";
        number.textContent = String(lineNumber);
        const text = document.createElement("span");
        text.className = "cm-sticky-scroll-text";
        const inner = document.createElement("span");
        inner.className = "cm-sticky-scroll-text-inner";
        renderLineText(view.state, lineNumber, inner);
        text.append(inner);
        row.append(number, text);
        return row;
      }));
    }
    this.dom.style.setProperty("--sticky-scroll-left", `${-measure.scrollLeft}px`);
    this.height = height;
  }
}

const stickyScrollPlugin = ViewPlugin.fromClass(StickyScrollController);

const stickyScrollTheme = EditorView.baseTheme({
  ".cm-sticky-scroll": {
    position: "absolute",
    left: "0",
    zIndex: "5",
    overflow: "hidden",
    backgroundColor: "var(--editor-bg)",
    boxShadow: "0 1px 0 var(--border), 0 6px 10px -8px var(--shadow-elevated-color, rgba(0, 0, 0, 0.35))",
    fontFamily: "var(--editor-font-family)",
    fontSize: "var(--editor-font-size)",
    fontVariantLigatures: "none",
  },
  ".cm-sticky-scroll[hidden]": {
    display: "none",
  },
  ".cm-sticky-scroll-row": {
    display: "flex",
    height: "var(--sticky-line-height)",
    lineHeight: "var(--sticky-line-height)",
    cursor: "pointer",
    whiteSpace: "pre",
  },
  ".cm-sticky-scroll-row:hover": {
    backgroundColor: "var(--editor-active-line-bg)",
  },
  ".cm-sticky-scroll-number": {
    flex: "none",
    boxSizing: "border-box",
    width: "var(--sticky-number-width)",
    // Mirrors the line number gutter: right aligned with the same inner padding.
    paddingRight: "3px",
    marginRight: "var(--sticky-gutter-rest)",
    textAlign: "right",
    color: "var(--editor-gutter-text)",
    fontSize: "var(--editor-gutter-font-size)",
  },
  ".cm-sticky-scroll-text": {
    flex: "1 1 auto",
    minWidth: "0",
    overflow: "hidden",
    paddingLeft: "6px",
    color: "var(--editor-text)",
  },
  ".cm-sticky-scroll-text-inner": {
    display: "inline-block",
    transform: "translateX(var(--sticky-scroll-left, 0px))",
  },
});

/** Keeps the headers of the scopes around the first visible line pinned to the top of the editor. */
export function createFileEditorStickyScroll(): Extension[] {
  return [
    stickyScrollPlugin,
    // Reveals and cursor movement must not land underneath the pinned rows.
    EditorView.scrollMargins.of((view) => {
      const height = view.plugin(stickyScrollPlugin)?.stickyHeight ?? 0;
      return height > 0 ? { top: height } : null;
    }),
    stickyScrollTheme,
  ];
}
