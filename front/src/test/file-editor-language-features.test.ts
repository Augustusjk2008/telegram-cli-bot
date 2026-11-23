import { cpp } from "@codemirror/lang-cpp";
import { python } from "@codemirror/lang-python";
import { ensureSyntaxTree } from "@codemirror/language";
import { EditorState, Text } from "@codemirror/state";
import { describe, expect, it } from "vitest";
import type { CodeSemanticTokens } from "../services/types";
import { detectFileEditorIndentUnit } from "../utils/fileEditorIndentGuides";
import {
  buildSemanticDecorations,
  codePointColumnToOffset,
  offsetToCodePointColumn,
  renderLanguageHover,
  resolveSemanticSlot,
} from "../utils/fileEditorLanguageFeatures";
import { classifyIdentifierSpelling, collectConventionMarks } from "../utils/fileEditorNameConventions";
import { resolveFileEditorScopeChain } from "../utils/fileEditorStickyScroll";

function parsedState(doc: string, language: ReturnType<typeof cpp>) {
  const state = EditorState.create({ doc, extensions: [language] });
  ensureSyntaxTree(state, state.doc.length, 5000);
  return state;
}

function decorationsOf(doc: Text, payload: CodeSemanticTokens) {
  const found: Array<{ from: number; to: number; className: string }> = [];
  buildSemanticDecorations(doc, payload).between(0, doc.length, (from, to, value) => {
    found.push({ from, to, className: String(value.spec.class) });
  });
  return found;
}

describe("semantic token decorations", () => {
  it("places tokens by code-point column on lines with astral characters", () => {
    const line = "x = \"😀\" + name";
    expect(codePointColumnToOffset(line, 11)).toBe(line.indexOf("name"));
    expect(offsetToCodePointColumn(line, line.indexOf("name"))).toBe(11);

    const doc = Text.of(["int value;", line]);
    const found = decorationsOf(doc, {
      legend: { types: ["variable", "keyword"], modifiers: [] },
      // The second token is a keyword, which syntax highlighting already colours.
      tokens: [2, 11, 4, 0, 0, 1, 1, 3, 1, 0],
      inactiveRanges: [],
      version: 1,
    });
    const from = doc.line(2).from + line.indexOf("name");
    expect(found).toEqual([{ from, to: from + 4, className: "cm-semantic-variable" }]);
  });

  it("dims preprocessor-disabled lines and ignores tokens outside the document", () => {
    const doc = Text.of(["#if 0", "int dead;", "#endif", "int live;"]);
    const found = decorationsOf(doc, {
      legend: { types: ["variable", "comment"], modifiers: [] },
      tokens: [
        4, 5, 4, 0, 0,
        // Disabled code reported as a comment token on a line without an inactive range.
        4, 1, 3, 1, 0,
        // A stale token past the end of the file.
        9, 1, 3, 0, 0,
      ],
      inactiveRanges: [{ startLine: 2, endLine: 2 }],
      version: 1,
    });
    expect(found).toEqual([
      { from: doc.line(2).from, to: doc.line(2).from, className: "cm-inactive-code" },
      { from: doc.line(4).from, to: doc.line(4).from + 3, className: "cm-inactive-code-text" },
      { from: doc.line(4).from + 4, to: doc.line(4).from + 8, className: "cm-semantic-variable" },
    ]);
  });

  it("keeps const locals as variables and file-level constants as constants", () => {
    expect(resolveSemanticSlot("variable", ["readonly", "functionScope"])).toBe("variable");
    expect(resolveSemanticSlot("variable", ["readonly", "fileScope"])).toBe("constant");
    // tsserver marks locals instead of scopes, and calls methods "member".
    expect(resolveSemanticSlot("variable", ["readonly"], ["readonly", "local"])).toBe("constant");
    expect(resolveSemanticSlot("variable", ["readonly", "local"], ["readonly", "local"])).toBe("variable");
    expect(resolveSemanticSlot("member", [])).toBe("function");
    expect(resolveSemanticSlot("enumMember", [])).toBe("constant");
    expect(resolveSemanticSlot("constructor", [])).toBeNull();
    expect(resolveSemanticSlot("keyword", [])).toBeNull();
  });
});

describe("language hover rendering", () => {
  it("never interprets server text as HTML", () => {
    const state = EditorState.create({ doc: "" });
    const dom = renderLanguageHover(state, [
      { kind: "markdown", value: "```cpp\nint <b>x</b>;\n```\n\n<img src=x onerror=alert(1)> `code` **bold**" },
    ]);
    expect(dom.querySelector("img")).toBeNull();
    expect(dom.querySelector("b")).toBeNull();
    expect(dom.querySelector("pre")?.textContent).toBe("int <b>x</b>;");
    expect(dom.querySelector("code")?.textContent).toBe("code");
    expect(dom.querySelector("strong")?.textContent).toBe("bold");
    expect(dom.textContent).toContain("<img src=x onerror=alert(1)>");
  });

  it("turns markdown rules into separators only between content", () => {
    const state = EditorState.create({ doc: "" });
    const dom = renderLanguageHover(state, [
      { kind: "markdown", value: "---\n### method `run`\n\n---\n→ `int`\n\n---\n```cpp\nint run();\n```\n---" },
    ]);
    expect(Array.from(dom.children).map((node) => node.nodeName)).toEqual(["P", "HR", "P", "HR", "PRE"]);
    expect(dom.textContent).not.toContain("---");
  });
});

describe("sticky scroll scopes", () => {
  it("lists the C++ scopes around a line, using the statement line for a lone brace", () => {
    const state = parsedState([
      "namespace demo {",         // 1
      "int run(int count)",       // 2
      "{",                        // 3
      "    for (;;) {",           // 4
      "        if (count) {",     // 5
      "            return 1;",    // 6
      "        }",                // 7
      "    }",                    // 8
      "}",                        // 9
      "}",                        // 10
    ].join("\n"), cpp());
    expect(resolveFileEditorScopeChain(state, 6).map((scope) => scope.headerLine)).toEqual([1, 2, 4, 5]);
    // A block's own header line is outside the block.
    expect(resolveFileEditorScopeChain(state, 4).map((scope) => scope.headerLine)).toEqual([1, 2]);
    expect(resolveFileEditorScopeChain(state, 1)).toEqual([]);
  });

  it("lists Python scopes by their header lines", () => {
    const state = parsedState([
      "class Service:",             // 1
      "    def run(self):",         // 2
      "        if self.ready:",     // 3
      "            return 1",       // 4
      "        return 0",           // 5
      "",                           // 6
      "",                           // 7
      "def main():",                // 8
      "    pass",                   // 9
    ].join("\n"), python() as ReturnType<typeof cpp>);
    expect(resolveFileEditorScopeChain(state, 4).map((scope) => scope.headerLine)).toEqual([1, 2, 3]);
    expect(resolveFileEditorScopeChain(state, 5).map((scope) => scope.headerLine)).toEqual([1, 2]);
    // Blank lines after a block belong to no scope, even though the grammar ends the block later.
    expect(resolveFileEditorScopeChain(state, 6)).toEqual([]);
    expect(resolveFileEditorScopeChain(state, 9).map((scope) => scope.headerLine)).toEqual([8]);
  });
});

describe("indentation detection", () => {
  it("reads the unit from how far lines step in", () => {
    expect(detectFileEditorIndentUnit(Text.of(["void f() {", "    if (x) {", "        y();", "    }", "}"]))).toBe("    ");
    expect(detectFileEditorIndentUnit(Text.of(["def f():", "  if x:", "    y()"]))).toBe("  ");
    expect(detectFileEditorIndentUnit(Text.of(["f() {", "\tg();", "\t\th();", "}"]))).toBe("\t");
    expect(detectFileEditorIndentUnit(Text.of(["plain", "text"]))).toBeNull();
  });
});

describe("naming convention colours", () => {
  it("reads types and constants from spelling", () => {
    expect(classifyIdentifierSpelling("StatusCode")).toBe("type");
    expect(classifyIdentifierSpelling("DEFAULT_LIMIT")).toBe("constant");
    expect(classifyIdentifierSpelling("value")).toBeNull();
    expect(classifyIdentifierSpelling("T")).toBeNull();
  });

  it("marks Python classes, constants, builtin types and self", () => {
    const doc = "from pathlib import Path\nLIMIT_MAX = 3\nclass Job:\n    def run(self, root: Path) -> str:\n        return str(self.name)\n";
    const state = parsedState(doc, python() as ReturnType<typeof cpp>);
    const found = collectConventionMarks(state, "python", 0, state.doc.length)
      .map((mark) => `${state.sliceDoc(mark.from, mark.to)}:${mark.slot}`);
    expect(found).toEqual([
      "from:control",
      "Path:type",
      "LIMIT_MAX:constant",
      "Job:type",
      "self:keyword",
      "Path:type",
      "str:type",
      "str:type",
      "self:keyword",
    ]);
  });

  it("never reads a capitalised C++ call or member as a type", () => {
    const state = parsedState("void f() { Buffer view; DoWork(view); obj.Reset(); int n = MAX_RETRY; }", cpp());
    const found = collectConventionMarks(state, "cpp", 0, state.doc.length)
      .map((mark) => `${state.sliceDoc(mark.from, mark.to)}:${mark.slot}`);
    expect(found).toEqual(["MAX_RETRY:constant"]);
  });
});
