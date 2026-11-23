import { getIndentUnit, indentUnit } from "@codemirror/language";
import { RangeSetBuilder, type Extension, type Text } from "@codemirror/state";
import { Decoration, EditorView, ViewPlugin, type DecorationSet, type ViewUpdate } from "@codemirror/view";

const DETECTION_LINE_LIMIT = 2000;
const SCOPE_SCAN_LINE_LIMIT = 3000;
const MAX_GUIDE_LEVELS = 40;

/** Leading whitespace width in columns, or -1 for a blank line. */
function indentColumns(text: string, tabSize: number) {
  let columns = 0;
  for (let index = 0; index < text.length; index += 1) {
    const char = text.charCodeAt(index);
    if (char === 32) {
      columns += 1;
    } else if (char === 9) {
      columns += tabSize - (columns % tabSize);
    } else {
      return columns;
    }
  }
  return -1;
}

/**
 * Guess the file's indentation unit from how far lines step in relative to the
 * line before them. Returns a string suitable for the `indentUnit` facet, or
 * null when the file gives no evidence.
 */
export function detectFileEditorIndentUnit(doc: Text): string | null {
  let tabLines = 0;
  let spaceLines = 0;
  const steps = new Map<number, number>();
  let previousSpaces = 0;
  const lineCount = Math.min(doc.lines, DETECTION_LINE_LIMIT);
  for (let number = 1; number <= lineCount; number += 1) {
    const text = doc.line(number).text;
    if (!text.trim()) continue;
    if (text.charCodeAt(0) === 9) {
      tabLines += 1;
      previousSpaces = 0;
      continue;
    }
    let spaces = 0;
    while (spaces < text.length && text.charCodeAt(spaces) === 32) spaces += 1;
    if (spaces > 0) spaceLines += 1;
    const step = spaces - previousSpaces;
    // Only a line stepping further in says something about the unit; closing a block can drop several levels.
    if (step >= 2 && step <= 8) steps.set(step, (steps.get(step) || 0) + 1);
    previousSpaces = spaces;
  }
  if (tabLines > spaceLines) return "\t";
  let best = 0;
  let bestCount = 0;
  for (const [step, count] of steps) {
    if (count > bestCount || (count === bestCount && step < best)) {
      best = step;
      bestCount = count;
    }
  }
  return best > 0 ? " ".repeat(best) : null;
}

type LineLevels = {
  levels: number;
  active: number;
};

function buildDecorations(view: EditorView): DecorationSet {
  const { state } = view;
  const { doc } = state;
  const tabSize = state.tabSize;
  const unit = Math.max(1, getIndentUnit(state));
  const cache = new Map<number, number>();
  const columnsOf = (number: number) => {
    let value = cache.get(number);
    if (value === undefined) {
      value = indentColumns(doc.line(number).text, tabSize);
      cache.set(number, value);
    }
    return value;
  };
  // A blank line continues the guides of the shallower of its neighbours.
  const effectiveColumns = (number: number) => {
    const own = columnsOf(number);
    if (own >= 0) return own;
    let before = -1;
    for (let line = number - 1; line >= 1 && number - line <= 200; line -= 1) {
      before = columnsOf(line);
      if (before >= 0) break;
    }
    let after = -1;
    for (let line = number + 1; line <= doc.lines && line - number <= 200; line += 1) {
      after = columnsOf(line);
      if (after >= 0) break;
    }
    if (before < 0 || after < 0) return 0;
    // Between a block header and its body the guides already belong to the body.
    return before < after ? (Math.floor(before / unit) + 1) * unit : after;
  };

  // The active guide is the one bounding the innermost block around the cursor.
  const cursorLine = doc.lineAt(state.selection.main.head).number;
  const cursorLevel = Math.floor(effectiveColumns(cursorLine) / unit);
  let activeFrom = 0;
  let activeTo = -1;
  if (cursorLevel > 0) {
    const minColumns = cursorLevel * unit;
    activeFrom = cursorLine;
    activeTo = cursorLine;
    for (let line = cursorLine - 1; line >= 1 && cursorLine - line <= SCOPE_SCAN_LINE_LIMIT; line -= 1) {
      const columns = columnsOf(line);
      if (columns >= 0 && columns < minColumns) break;
      activeFrom = line;
    }
    for (let line = cursorLine + 1; line <= doc.lines && line - cursorLine <= SCOPE_SCAN_LINE_LIMIT; line += 1) {
      const columns = columnsOf(line);
      if (columns >= 0 && columns < minColumns) break;
      activeTo = line;
    }
  }

  const builder = new RangeSetBuilder<Decoration>();
  const decorationCache = new Map<string, Decoration>();
  const decorationFor = ({ levels, active }: LineLevels) => {
    const key = `${levels}:${active}`;
    let decoration = decorationCache.get(key);
    if (!decoration) {
      decoration = Decoration.line({
        class: active >= 0 ? "cm-indent-guides cm-indent-guides-active" : "cm-indent-guides",
        attributes: {
          style: `--indent-guide-levels:${levels};--indent-guide-active:${Math.max(0, active)}`,
        },
      });
      decorationCache.set(key, decoration);
    }
    return decoration;
  };

  for (const { from, to } of view.visibleRanges) {
    let position = from;
    while (position <= to) {
      const line = doc.lineAt(position);
      const levels = Math.min(MAX_GUIDE_LEVELS, Math.floor(effectiveColumns(line.number) / unit));
      if (levels > 0) {
        const active = line.number >= activeFrom && line.number <= activeTo && cursorLevel <= levels
          ? cursorLevel - 1
          : -1;
        builder.add(line.from, line.from, decorationFor({ levels, active }));
      }
      position = line.to + 1;
    }
  }
  return builder.finish();
}

const indentGuidesPlugin = ViewPlugin.fromClass(class {
  decorations: DecorationSet;

  constructor(view: EditorView) {
    this.decorations = buildDecorations(view);
  }

  update(update: ViewUpdate) {
    const cursorLineChanged = update.selectionSet
      && update.startState.doc.lineAt(update.startState.selection.main.head).number
        !== update.state.doc.lineAt(update.state.selection.main.head).number;
    if (
      update.docChanged
      || update.viewportChanged
      || cursorLineChanged
      || update.startState.facet(indentUnit) !== update.state.facet(indentUnit)
      || update.startState.tabSize !== update.state.tabSize
    ) {
      this.decorations = buildDecorations(update.view);
    }
  }
}, {
  decorations: (plugin) => plugin.decorations,
});

// Guides are painted as line backgrounds so they add no DOM and never shift text.
const indentGuidesTheme = EditorView.baseTheme({
  ".cm-line.cm-indent-guides": {
    "--indent-guide-step": "calc(var(--indent-guide-unit, 4) * 1ch)",
    backgroundImage:
      "repeating-linear-gradient(to right, var(--editor-indent-guide, var(--border)) 0 1px, transparent 1px var(--indent-guide-step))",
    backgroundRepeat: "no-repeat",
    backgroundSize: "calc(var(--indent-guide-levels) * var(--indent-guide-step)) 100%",
    backgroundPosition: "6px 0",
  },
  ".cm-line.cm-indent-guides.cm-indent-guides-active": {
    backgroundImage:
      "linear-gradient(var(--editor-indent-guide-active, var(--border-strong, var(--border))), var(--editor-indent-guide-active, var(--border-strong, var(--border)))), "
      + "repeating-linear-gradient(to right, var(--editor-indent-guide, var(--border)) 0 1px, transparent 1px var(--indent-guide-step))",
    backgroundSize: "1px 100%, calc(var(--indent-guide-levels) * var(--indent-guide-step)) 100%",
    backgroundPosition: "calc(6px + var(--indent-guide-active) * var(--indent-guide-step)) 0, 6px 0",
  },
});

/** Indentation guides, plus the file's own indentation unit when it can be detected. */
export function createFileEditorIndentGuides(doc: Text | null): Extension[] {
  const detected = doc ? detectFileEditorIndentUnit(doc) : null;
  return [
    ...(detected ? [indentUnit.of(detected)] : []),
    EditorView.contentAttributes.of((view) => ({
      style: `--indent-guide-unit:${Math.max(1, getIndentUnit(view.state))}`,
    })),
    indentGuidesPlugin,
    indentGuidesTheme,
  ];
}
