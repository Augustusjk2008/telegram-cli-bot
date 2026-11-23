import {
  autocompletion,
  insertCompletionText,
  type Completion,
  type CompletionContext,
  type CompletionResult,
  type CompletionSource,
} from "@codemirror/autocomplete";
import { language } from "@codemirror/language";
import { setDiagnostics, type Diagnostic } from "@codemirror/lint";
import { Prec, StateEffect, StateField, type EditorState, type Extension, type Text } from "@codemirror/state";
import {
  Decoration,
  EditorView,
  ViewPlugin,
  hoverTooltip,
  tooltips,
  type DecorationSet,
  type Tooltip,
  type ViewUpdate,
} from "@codemirror/view";
import { highlightTree } from "@lezer/highlight";
import type {
  CodeCompletionItem,
  CodeDiagnostic,
  CodeHoverContent,
  CodeIntelligenceKind,
  CodeIntelligenceResult,
  CodePosition,
  CodeSemanticTokens,
} from "../services/types";
import {
  FILE_EDITOR_HIGHLIGHT_STYLE,
  FILE_EDITOR_SYNTAX_COLORS,
  type FileEditorSyntaxSlot,
} from "./fileEditorHighlight";

export type FileEditorLanguageFeatureQuery = {
  kind: CodeIntelligenceKind;
  position?: CodePosition;
  context?: { triggerCharacter?: string; includeDeclaration?: boolean };
  waitMs?: number;
};

/**
 * Sends one language query for the document. `content` is the text the caller
 * computed positions against; resolve null when that text is no longer current.
 */
export type FileEditorLanguageFeatureRequest = (
  query: FileEditorLanguageFeatureQuery,
  content: string,
  signal: AbortSignal,
) => Promise<CodeIntelligenceResult | null>;

export type FileEditorLanguageFeatureOptions = {
  request: FileEditorLanguageFeatureRequest;
  hover?: boolean;
  semanticTokens?: boolean;
  diagnostics?: boolean;
  completion?: boolean;
  refreshDelayMs?: number;
};

const MAX_FEATURE_DOCUMENT_LENGTH = 200_000;
const DEFAULT_REFRESH_DELAY_MS = 350;
const DIAGNOSTIC_WAIT_MS = 2000;
const DIAGNOSTIC_RETRY_LIMIT = 4;
const DIAGNOSTIC_RETRY_DELAY_MS = 1500;
const SURROGATE_PATTERN = /[\uD800-\uDFFF]/;

/** Converts a 1-based code-point column to a UTF-16 offset inside the line. */
export function codePointColumnToOffset(lineText: string, column: number) {
  const target = Math.max(0, column - 1);
  if (target >= lineText.length || !SURROGATE_PATTERN.test(lineText)) {
    return Math.min(target, lineText.length);
  }
  let offset = 0;
  for (let count = 0; count < target && offset < lineText.length; count += 1) {
    const code = lineText.charCodeAt(offset);
    offset += code >= 0xd800 && code <= 0xdbff && offset + 1 < lineText.length ? 2 : 1;
  }
  return offset;
}

/** Converts a UTF-16 offset inside the line to a 1-based code-point column. */
export function offsetToCodePointColumn(lineText: string, offset: number) {
  const bounded = Math.min(Math.max(0, offset), lineText.length);
  if (!SURROGATE_PATTERN.test(lineText)) return bounded + 1;
  return Array.from(lineText.slice(0, bounded)).length + 1;
}

export function codePositionToOffset(doc: Text, position: CodePosition): number | null {
  if (position.line < 1 || position.line > doc.lines) return null;
  const line = doc.line(position.line);
  return line.from + codePointColumnToOffset(line.text, position.column);
}

export function offsetToCodePosition(doc: Text, offset: number): CodePosition {
  const line = doc.lineAt(offset);
  return { line: line.number, column: offsetToCodePointColumn(line.text, offset - line.from) };
}

const SEMANTIC_TYPE_SLOTS: Record<string, FileEditorSyntaxSlot> = {
  namespace: "namespace",
  module: "namespace",
  type: "type",
  class: "type",
  enum: "type",
  interface: "type",
  struct: "type",
  typeParameter: "type",
  concept: "type",
  parameter: "variable",
  variable: "variable",
  selfParameter: "variable",
  clsParameter: "variable",
  property: "property",
  field: "property",
  // tsserver calls methods "member".
  member: "function",
  enumMember: "constant",
  event: "property",
  function: "function",
  method: "function",
  magicFunction: "function",
  decorator: "function",
  macro: "meta",
  label: "constant",
};

/**
 * Slot for one semantic token, or null when the syntax colour should stay.
 * Keywords, literals, comments and operators are already right from syntax.
 * `legendModifiers` is the server's full modifier list: servers mark scope in
 * different ways, and an absent marker only means something if the server has it.
 */
export function resolveSemanticSlot(
  type: string,
  modifiers: readonly string[],
  legendModifiers: readonly string[] = [],
): FileEditorSyntaxSlot | null {
  if (!Object.prototype.hasOwnProperty.call(SEMANTIC_TYPE_SLOTS, type)) return null;
  const slot = SEMANTIC_TYPE_SLOTS[type];
  if (type === "variable" && modifiers.includes("readonly")) {
    // Only variables that outlive a call read as constants; `const` locals stay ordinary variables.
    const outlivesCall = modifiers.includes("globalScope")
      || modifiers.includes("fileScope")
      || modifiers.includes("static")
      || (legendModifiers.includes("local") && !modifiers.includes("local"));
    if (outlivesCall) return "constant";
  }
  return slot;
}

const semanticMarks = new Map<string, Decoration>();

function semanticMark(slot: FileEditorSyntaxSlot) {
  let mark = semanticMarks.get(slot);
  if (!mark) {
    mark = Decoration.mark({ class: `cm-semantic-${slot}` });
    semanticMarks.set(slot, mark);
  }
  return mark;
}

const inactiveLine = Decoration.line({ class: "cm-inactive-code" });
const inactiveMark = Decoration.mark({ class: "cm-inactive-code-text" });

/** Builds editor decorations from a semantic token payload computed for `doc`. */
export function buildSemanticDecorations(doc: Text, payload: CodeSemanticTokens): DecorationSet {
  const { tokens, legend } = payload;
  const modifierCache = new Map<number, string[]>();
  const modifiersOf = (bits: number) => {
    let names = modifierCache.get(bits);
    if (!names) {
      names = legend.modifiers.filter((_, index) => index < 31 && (bits & (1 << index)) !== 0);
      modifierCache.set(bits, names);
    }
    return names;
  };
  const inactiveLines = new Set<number>();
  const ranges = [];
  for (const range of payload.inactiveRanges) {
    const last = Math.min(range.endLine, doc.lines);
    for (let number = Math.max(1, range.startLine); number <= last; number += 1) {
      if (inactiveLines.has(number)) continue;
      inactiveLines.add(number);
      ranges.push(inactiveLine.range(doc.line(number).from));
    }
  }
  let cachedNumber = 0;
  let cachedLine = doc.line(1);
  for (let index = 0; index + 4 < tokens.length; index += 5) {
    const lineNumber = tokens[index];
    const length = tokens[index + 2];
    if (lineNumber < 1 || lineNumber > doc.lines || length <= 0) continue;
    const type = legend.types[tokens[index + 3]] || "";
    // Servers without an inactive-region notification report disabled code as comment tokens.
    const inactive = type === "comment";
    const slot = inactive ? null : resolveSemanticSlot(type, modifiersOf(tokens[index + 4]), legend.modifiers);
    if (!slot && !(inactive && !inactiveLines.has(lineNumber))) continue;
    if (lineNumber !== cachedNumber) {
      cachedNumber = lineNumber;
      cachedLine = doc.line(lineNumber);
    }
    const column = tokens[index + 1];
    const from = codePointColumnToOffset(cachedLine.text, column);
    const to = codePointColumnToOffset(cachedLine.text, column + length);
    if (to <= from) continue;
    ranges.push((slot ? semanticMark(slot) : inactiveMark).range(cachedLine.from + from, cachedLine.from + to));
  }
  return Decoration.set(ranges, true);
}

const setSemanticDecorations = StateEffect.define<DecorationSet>();

const semanticDecorationField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(value, transaction) {
    for (const effect of transaction.effects) {
      if (effect.is(setSemanticDecorations)) return effect.value;
    }
    // Colours travel with the text until the next refresh replaces them.
    return transaction.docChanged ? value.map(transaction.changes) : value;
  },
  provide: (field) => EditorView.decorations.from(field),
});

/** Ask the feature controller to refetch, e.g. after the language server finished indexing. */
export const refreshFileEditorLanguageFeatures = StateEffect.define<null>();

const SEMANTIC_SLOTS: FileEditorSyntaxSlot[] = [
  "namespace",
  "type",
  "variable",
  "property",
  "constant",
  "function",
  "meta",
];

const languageFeatureTheme = EditorView.baseTheme({
  ...Object.fromEntries(SEMANTIC_SLOTS.map((slot) => [
    `.cm-semantic-${slot}`,
    { color: FILE_EDITOR_SYNTAX_COLORS[slot] },
  ])),
  ".cm-inactive-code, .cm-inactive-code-text": {
    opacity: "0.55",
  },
  ".cm-tooltip.cm-tooltip-hover": {
    border: "1px solid var(--border)",
    borderRadius: "6px",
    boxShadow: "var(--shadow-float)",
  },
  ".cm-language-hover": {
    maxWidth: "min(560px, 80vw)",
    maxHeight: "min(320px, 50vh)",
    overflow: "auto",
    padding: "6px 10px",
    fontFamily: "var(--chat-body-font-family)",
    fontSize: "12.5px",
    lineHeight: "1.55",
    color: "var(--editor-completion-text)",
  },
  ".cm-language-hover p": {
    margin: "4px 0",
    whiteSpace: "pre-wrap",
    overflowWrap: "anywhere",
  },
  ".cm-language-hover pre": {
    margin: "4px 0",
    padding: "0",
    whiteSpace: "pre-wrap",
    overflowWrap: "anywhere",
    fontFamily: "var(--editor-font-family)",
    fontSize: "12.5px",
    fontVariantLigatures: "none",
    color: "var(--editor-text)",
  },
  ".cm-language-hover code": {
    fontFamily: "var(--editor-font-family)",
    fontVariantLigatures: "none",
  },
  ".cm-language-hover hr": {
    margin: "6px 0",
    border: "0",
    borderTop: "1px solid var(--border)",
  },
});

function appendInlineMarkdown(target: HTMLElement, text: string) {
  // Language servers escape markdown punctuation in plain prose; undo that before splitting.
  const pattern = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\[[^\]\n]+\]\([^)\n]*\))/g;
  let position = 0;
  const pushText = (value: string) => {
    if (value) target.append(value.replace(/\\([\\`*_{}[\]()#+\-.!<>|~])/g, "$1").replace(/&nbsp;/g, " "));
  };
  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0;
    pushText(text.slice(position, index));
    const token = match[0];
    if (token.startsWith("`")) {
      const code = document.createElement("code");
      code.textContent = token.slice(1, -1);
      target.append(code);
    } else if (token.startsWith("**")) {
      const strong = document.createElement("strong");
      strong.textContent = token.slice(2, -2);
      target.append(strong);
    } else {
      pushText(token.slice(1, token.indexOf("](")));
    }
    position = index + token.length;
  }
  pushText(text.slice(position));
}

function appendHighlightedCode(target: HTMLElement, state: EditorState, code: string) {
  const parser = state.facet(language)?.parser;
  if (!parser || code.length > 20_000) {
    target.textContent = code;
    return;
  }
  let position = 0;
  highlightTree(parser.parse(code), FILE_EDITOR_HIGHLIGHT_STYLE, (from, to, classes) => {
    if (from > position) target.append(code.slice(position, from));
    const span = document.createElement("span");
    span.className = classes;
    span.textContent = code.slice(from, to);
    target.append(span);
    position = to;
  });
  if (position < code.length) target.append(code.slice(position));
}

/** Renders hover text as DOM nodes; nothing from the server is ever parsed as HTML. */
export function renderLanguageHover(state: EditorState, contents: readonly CodeHoverContent[]) {
  const root = document.createElement("div");
  root.className = "cm-language-hover";
  // Rules only separate content: none at the edges, never two in a row.
  const appendRule = () => {
    if (root.lastChild && root.lastChild.nodeName !== "HR") root.append(document.createElement("hr"));
  };
  for (const content of contents) {
    appendRule();
    if (content.kind !== "markdown") {
      const text = content.value.trim();
      if (!text) continue;
      const paragraph = document.createElement("p");
      paragraph.textContent = text;
      root.append(paragraph);
      continue;
    }
    content.value.split(/```/).forEach((segment, index) => {
      if (index % 2 === 1) {
        const newline = segment.indexOf("\n");
        const code = (newline >= 0 ? segment.slice(newline + 1) : segment).replace(/\s+$/, "");
        if (!code) return;
        const pre = document.createElement("pre");
        appendHighlightedCode(pre, state, code);
        root.append(pre);
        return;
      }
      let paragraph: HTMLElement | null = null;
      for (const line of segment.split("\n")) {
        if (!line.trim()) {
          paragraph = null;
          continue;
        }
        if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
          paragraph = null;
          appendRule();
          continue;
        }
        if (paragraph) {
          paragraph.append("\n");
        } else {
          paragraph = document.createElement("p");
          root.append(paragraph);
        }
        const heading = line.match(/^\s*#{1,6}\s+(.*)$/);
        if (heading) {
          const strong = document.createElement("strong");
          appendInlineMarkdown(strong, heading[1]);
          paragraph.append(strong);
        } else {
          appendInlineMarkdown(paragraph, line.replace(/^(\s*)[-*+]\s+/, "$1• "));
        }
      }
    });
  }
  if (root.lastChild?.nodeName === "HR") root.lastChild.remove();
  return root;
}

function toLintDiagnostics(doc: Text, items: readonly CodeDiagnostic[]): Diagnostic[] {
  const diagnostics: Diagnostic[] = [];
  for (const item of items) {
    // Hints mostly mark unused code, which an underline would overstate.
    if (item.severity === "hint") continue;
    const from = codePositionToOffset(doc, item.range.start);
    const end = codePositionToOffset(doc, item.range.end);
    if (from === null) continue;
    const to = Math.max(from, end ?? from);
    const lineEnd = doc.lineAt(from).to;
    diagnostics.push({
      from,
      // A zero-width range would be invisible; widen it to one character where the line allows.
      to: to > from ? to : Math.min(from + 1, lineEnd),
      severity: item.severity,
      message: item.message,
      source: [item.source, item.code].filter(Boolean).join(" ") || undefined,
    });
  }
  return diagnostics.sort((left, right) => left.from - right.from);
}

const COMPLETION_TYPES: Record<string, string> = {
  method: "method",
  function: "function",
  constructor: "function",
  field: "property",
  property: "property",
  variable: "variable",
  value: "variable",
  reference: "variable",
  class: "class",
  struct: "class",
  interface: "interface",
  module: "namespace",
  file: "namespace",
  folder: "namespace",
  enum: "enum",
  enumMember: "constant",
  constant: "constant",
  keyword: "keyword",
  typeParameter: "type",
};

function toCompletion(
  item: CodeCompletionItem,
  index: number,
  total: number,
  doc: Text,
  cursor: number,
): Completion {
  const display = item.label.replace(/^[\s•]+/, "").trimEnd();
  const label = item.filterText.trim() || display;
  const editFrom = item.textEdit ? codePositionToOffset(doc, item.textEdit.range.start) : null;
  const insert = item.textEdit ? item.textEdit.newText : item.insertText;
  return {
    label,
    ...(display && display !== label ? { displayLabel: display } : {}),
    ...(item.detail ? { detail: item.detail } : {}),
    ...(item.documentation ? { info: item.documentation } : {}),
    type: COMPLETION_TYPES[item.kind] || "text",
    // Keep the server's ranking among equally good matches.
    boost: Math.round(99 - (index * 198) / Math.max(1, total - 1)),
    apply: editFrom !== null && editFrom <= cursor && doc.lineAt(editFrom).number === doc.lineAt(cursor).number
      ? (view, _completion, _from, to) => {
          view.dispatch(insertCompletionText(view.state, insert, editFrom, to));
        }
      : insert,
  };
}

const COMPLETION_TRIGGERS = [".", "->", "::", "\"", "/", "<", "@", "#"];

/** Trigger text right before the cursor, or "" when the cursor does not follow one. */
function completionTriggerBefore(context: CompletionContext) {
  const before = context.state.sliceDoc(Math.max(0, context.pos - 2), context.pos);
  return COMPLETION_TRIGGERS.find((trigger) => before.endsWith(trigger)) || "";
}

class LanguageFeatureController {
  private timer: number | null = null;
  private retryTimer: number | null = null;
  private abortController: AbortController | null = null;
  private destroyed = false;
  // A server that cannot serve a feature is not asked again until a refresh is requested.
  private semanticTokensUnavailable = false;
  private diagnosticsUnavailable = false;
  /** Whether the last completion answer came from a language server. */
  serverCompletion = false;

  constructor(
    private readonly view: EditorView,
    private readonly options: FileEditorLanguageFeatureOptions,
  ) {
    this.schedule(0);
  }

  update(update: ViewUpdate) {
    const requested = update.transactions.some((transaction) => (
      transaction.effects.some((effect) => effect.is(refreshFileEditorLanguageFeatures))
    ));
    if (requested) {
      this.semanticTokensUnavailable = false;
      this.diagnosticsUnavailable = false;
      this.schedule(0);
    } else if (update.docChanged) {
      this.schedule(this.options.refreshDelayMs ?? DEFAULT_REFRESH_DELAY_MS);
    }
  }

  destroy() {
    this.destroyed = true;
    this.cancel();
  }

  private cancel() {
    if (this.timer !== null) window.clearTimeout(this.timer);
    if (this.retryTimer !== null) window.clearTimeout(this.retryTimer);
    this.timer = null;
    this.retryTimer = null;
    this.abortController?.abort();
    this.abortController = null;
  }

  private schedule(delay: number) {
    if (this.destroyed || (!this.options.semanticTokens && !this.options.diagnostics)) return;
    this.cancel();
    this.timer = window.setTimeout(() => {
      this.timer = null;
      void this.refresh();
    }, Math.max(0, delay));
  }

  private async refresh() {
    const doc = this.view.state.doc;
    if (doc.length > MAX_FEATURE_DOCUMENT_LENGTH) return;
    const wantsSemanticTokens = Boolean(this.options.semanticTokens) && !this.semanticTokensUnavailable;
    const wantsDiagnostics = Boolean(this.options.diagnostics) && !this.diagnosticsUnavailable;
    if (!wantsSemanticTokens && !wantsDiagnostics) return;
    const controller = new AbortController();
    this.abortController = controller;
    const content = doc.toString();
    const isCurrent = () => !this.destroyed && !controller.signal.aborted && this.view.state.doc === doc;
    const tasks: Promise<void>[] = [];
    if (wantsSemanticTokens) {
      tasks.push(this.refreshSemanticTokens(content, doc, controller.signal, isCurrent));
    }
    if (wantsDiagnostics) {
      tasks.push(this.refreshDiagnostics(content, doc, controller.signal, isCurrent, 0));
    }
    await Promise.all(tasks);
    if (this.abortController === controller) this.abortController = null;
  }

  private async refreshSemanticTokens(content: string, doc: Text, signal: AbortSignal, isCurrent: () => boolean) {
    try {
      const result = await this.options.request({ kind: "semanticTokens" }, content, signal);
      if (!result || !isCurrent()) return;
      this.semanticTokensUnavailable = !result.available || !result.supported;
      const decorations = this.semanticTokensUnavailable
        ? Decoration.none
        : buildSemanticDecorations(doc, result.semanticTokens);
      this.view.dispatch({ effects: setSemanticDecorations.of(decorations) });
    } catch {
      // Semantic colours are an enhancement; syntax highlighting already covers the file.
    }
  }

  private async refreshDiagnostics(
    content: string,
    doc: Text,
    signal: AbortSignal,
    isCurrent: () => boolean,
    attempt: number,
  ) {
    try {
      const result = await this.options.request({ kind: "diagnostics", waitMs: DIAGNOSTIC_WAIT_MS }, content, signal);
      if (!result || !isCurrent()) return;
      if (!result.available || !result.supported) {
        this.diagnosticsUnavailable = true;
        this.view.dispatch(setDiagnostics(this.view.state, []));
        return;
      }
      if (result.diagnostics.ready || result.diagnostics.items.length > 0) {
        this.view.dispatch(setDiagnostics(this.view.state, toLintDiagnostics(doc, result.diagnostics.items)));
      }
      if (!result.diagnostics.ready && attempt + 1 < DIAGNOSTIC_RETRY_LIMIT) {
        // The first analysis of a translation unit can outlast one wait window.
        this.retryTimer = window.setTimeout(() => {
          this.retryTimer = null;
          if (isCurrent()) void this.refreshDiagnostics(content, doc, signal, isCurrent, attempt + 1);
        }, DIAGNOSTIC_RETRY_DELAY_MS);
      }
    } catch {
      // Diagnostics stay as they were when a request fails.
    }
  }
}

/**
 * Language-server backed colours, hover cards, diagnostics and completion.
 * Every feature degrades to nothing when the server cannot answer.
 */
export function createFileEditorLanguageFeatures(options: FileEditorLanguageFeatureOptions): Extension[] {
  const controllerPlugin = ViewPlugin.define((view) => new LanguageFeatureController(view, options));
  const extensions: Extension[] = [
    // Highest precedence nests semantic marks innermost, so their colour beats syntax and convention colours.
    Prec.highest(semanticDecorationField),
    controllerPlugin,
    languageFeatureTheme,
    // The editor sits inside clipped glass panels; cards must escape them.
    tooltips({ parent: document.body }),
  ];

  if (options.hover) {
    let hoverAbort: AbortController | null = null;
    extensions.push(hoverTooltip(async (view, position): Promise<Tooltip | null> => {
      const { doc } = view.state;
      if (doc.length > MAX_FEATURE_DOCUMENT_LENGTH) return null;
      const word = view.state.wordAt(position);
      if (!word || position < word.from || position > word.to) return null;
      hoverAbort?.abort();
      const controller = new AbortController();
      hoverAbort = controller;
      try {
        const result = await options.request(
          { kind: "hover", position: offsetToCodePosition(doc, position) },
          doc.toString(),
          controller.signal,
        );
        if (!result || controller.signal.aborted || view.state.doc !== doc || result.hover.contents.length === 0) {
          return null;
        }
        const { state } = view;
        const contents = result.hover.contents;
        return {
          pos: word.from,
          end: word.to,
          above: true,
          create: () => ({ dom: renderLanguageHover(state, contents) }),
        };
      } catch {
        return null;
      } finally {
        if (hoverAbort === controller) hoverAbort = null;
      }
    }, { hoverTime: 400, hideOnChange: true }));
  }

  if (options.completion) {
    const serverSource: CompletionSource = async (context): Promise<CompletionResult | null> => {
      const { doc } = context.state;
      if (doc.length > MAX_FEATURE_DOCUMENT_LENGTH) return null;
      const word = context.matchBefore(/[\w$]+/);
      const trigger = word ? "" : completionTriggerBefore(context);
      if (!context.explicit && !word && !trigger) return null;
      const controller = new AbortController();
      context.addEventListener("abort", () => controller.abort());
      const controllerInstance = context.view?.plugin(controllerPlugin);
      try {
        const result = await options.request(
          {
            kind: "completion",
            position: offsetToCodePosition(doc, context.pos),
            ...(trigger ? { context: { triggerCharacter: trigger.slice(-1) } } : {}),
          },
          doc.toString(),
          controller.signal,
        );
        if (!result || controller.signal.aborted) return null;
        const served = result.available && result.supported;
        if (controllerInstance) controllerInstance.serverCompletion = served;
        const items = result.completion.items;
        if (!served || items.length === 0) return null;
        return {
          from: word ? word.from : context.pos,
          options: items.map((item, index) => toCompletion(item, index, items.length, doc, context.pos)),
          // An incomplete list must be refetched as the word grows.
          ...(result.completion.isIncomplete ? {} : { validFor: /^[\w$]*$/ }),
        };
      } catch {
        return null;
      }
    };
    // Language packages add word and keyword sources; they would only duplicate a server's answer.
    const languageSource = (index: number): CompletionSource => (context) => {
      if (context.view?.plugin(controllerPlugin)?.serverCompletion) return null;
      const source = context.state.languageDataAt<CompletionSource>("autocomplete", context.pos)[index];
      return source ? source(context) : null;
    };
    extensions.push(Prec.high(autocompletion({
      override: [serverSource, languageSource(0), languageSource(1), languageSource(2), languageSource(3)],
    })));
  }

  return extensions;
}
