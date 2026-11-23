import { syntaxTree } from "@codemirror/language";
import { Prec, type EditorState, type Extension, type Range } from "@codemirror/state";
import { Decoration, EditorView, ViewPlugin, type DecorationSet, type ViewUpdate } from "@codemirror/view";
import { FILE_EDITOR_SYNTAX_COLORS, type FileEditorSyntaxSlot } from "./fileEditorHighlight";

type ConventionLanguage = "python" | "javascript" | "cpp";
type ConventionSlot = Extract<FileEditorSyntaxSlot, "type" | "constant" | "keyword" | "control">;

type LanguageRules = {
  /** Identifier nodes worth classifying by their spelling. */
  identifiers: ReadonlySet<string>;
  /** Parents under which a capitalised name is a function, not a type. */
  functionParents: ReadonlySet<string>;
  words: ReadonlyMap<string, ConventionSlot>;
  /** Keyword nodes whose colour depends on more than the grammar's tag. */
  keywords: ReadonlyMap<string, ConventionSlot>;
};

const PYTHON_BUILTIN_TYPES = [
  "bool", "bytearray", "bytes", "complex", "dict", "float", "frozenset", "int", "list", "memoryview",
  "object", "set", "str", "tuple", "type",
];

const RULES: Record<ConventionLanguage, LanguageRules> = {
  python: {
    identifiers: new Set(["VariableName", "PropertyName"]),
    functionParents: new Set(),
    words: new Map<string, ConventionSlot>([
      ["self", "keyword"],
      ["cls", "keyword"],
      ...PYTHON_BUILTIN_TYPES.map((name): [string, ConventionSlot] => [name, "type"]),
    ]),
    // The grammar files `from` with `def` and `class`; it belongs with `import`.
    keywords: new Map<string, ConventionSlot>([["from", "control"]]),
  },
  javascript: {
    identifiers: new Set(["VariableName", "VariableDefinition", "PropertyName", "PropertyDefinition"]),
    functionParents: new Set(),
    words: new Map(),
    keywords: new Map(),
  },
  cpp: {
    identifiers: new Set(["Identifier", "FieldIdentifier"]),
    // Many C++ code bases capitalise functions, so a call or declarator name is never read as a type.
    functionParents: new Set(["CallExpression", "FunctionDeclarator", "FieldExpression", "ScopedIdentifier"]),
    words: new Map(),
    keywords: new Map(),
  },
};

const CONSTANT_PATTERN = /^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$/;
const TYPE_PATTERN = /^[A-Z][A-Za-z0-9]*[a-z][A-Za-z0-9]*$/;

/** Colour slot implied by how a name is written, or null when the spelling says nothing. */
export function classifyIdentifierSpelling(name: string): "type" | "constant" | null {
  if (name.length < 2) return null;
  if (CONSTANT_PATTERN.test(name)) return /[A-Z].*[A-Z_]/.test(name) ? "constant" : null;
  return TYPE_PATTERN.test(name) ? "type" : null;
}

export function resolveConventionLanguage(languageId: string): ConventionLanguage | null {
  if (languageId === "python") return "python";
  if (languageId === "cpp") return "cpp";
  if (/^(javascript|typescript)(react)?$/.test(languageId)) return "javascript";
  return null;
}

const marks: Record<ConventionSlot, Decoration> = {
  type: Decoration.mark({ class: "cm-convention-type" }),
  constant: Decoration.mark({ class: "cm-convention-constant" }),
  keyword: Decoration.mark({ class: "cm-convention-keyword" }),
  control: Decoration.mark({ class: "cm-convention-control" }),
};

/** Convention-based marks for a document range, in document order. */
export function collectConventionMarks(
  state: EditorState,
  language: ConventionLanguage,
  from: number,
  to: number,
): Array<{ from: number; to: number; slot: ConventionSlot }> {
  const rules = RULES[language];
  const found: Array<{ from: number; to: number; slot: ConventionSlot }> = [];
  syntaxTree(state).iterate({
    from,
    to,
    enter(node) {
      const keyword = rules.keywords.get(node.name);
      if (keyword) {
        found.push({ from: node.from, to: node.to, slot: keyword });
        return;
      }
      if (!rules.identifiers.has(node.name) || node.to - node.from > 80) return;
      const name = state.sliceDoc(node.from, node.to);
      let slot: ConventionSlot | null = rules.words.get(name) ?? classifyIdentifierSpelling(name);
      if (slot === "type" && rules.functionParents.size > 0) {
        const parent = node.node.parent;
        if (parent && rules.functionParents.has(parent.name)) slot = null;
      }
      if (slot) found.push({ from: node.from, to: node.to, slot });
    },
  });
  return found;
}

function buildDecorations(view: EditorView, language: ConventionLanguage): DecorationSet {
  const ranges: Range<Decoration>[] = [];
  for (const { from, to } of view.visibleRanges) {
    for (const mark of collectConventionMarks(view.state, language, from, to)) {
      ranges.push(marks[mark.slot].range(mark.from, mark.to));
    }
  }
  return Decoration.set(ranges, true);
}

const conventionTheme = EditorView.baseTheme({
  ".cm-convention-type": { color: FILE_EDITOR_SYNTAX_COLORS.type },
  ".cm-convention-constant": { color: FILE_EDITOR_SYNTAX_COLORS.constant },
  ".cm-convention-keyword": { color: FILE_EDITOR_SYNTAX_COLORS.keyword },
  ".cm-convention-control": { color: FILE_EDITOR_SYNTAX_COLORS.control },
});

/**
 * Colours names by convention (PascalCase types, UPPER_CASE constants, a few
 * language words) where the grammar alone cannot tell. It is a guess that a
 * language server's semantic tokens override wherever they exist.
 */
export function createFileEditorNameConventions(languageId: string): Extension[] {
  const language = resolveConventionLanguage(languageId);
  if (!language) return [];
  const plugin = ViewPlugin.fromClass(class {
    decorations: DecorationSet;

    constructor(view: EditorView) {
      this.decorations = buildDecorations(view, language);
    }

    update(update: ViewUpdate) {
      if (
        update.docChanged
        || update.viewportChanged
        || syntaxTree(update.startState) !== syntaxTree(update.state)
      ) {
        this.decorations = buildDecorations(update.view, language);
      }
    }
  }, {
    decorations: (value) => value.decorations,
  });
  // Highest precedence nests these marks inside the syntax highlighter's spans, so their colour applies.
  return [Prec.highest(plugin), conventionTheme];
}
