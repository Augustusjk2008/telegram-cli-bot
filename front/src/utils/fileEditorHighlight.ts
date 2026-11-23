import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { tags } from "@lezer/highlight";

/**
 * Editor colour slots. The newer slots fall back to an older one so a theme
 * that predates them still renders every token.
 */
export const FILE_EDITOR_SYNTAX_COLORS = {
  comment: "var(--editor-syntax-comment)",
  keyword: "var(--editor-syntax-keyword)",
  control: "var(--editor-syntax-control, var(--editor-syntax-keyword))",
  string: "var(--editor-syntax-string)",
  number: "var(--editor-syntax-number)",
  constant: "var(--editor-syntax-constant, var(--editor-syntax-number))",
  type: "var(--editor-syntax-type)",
  namespace: "var(--editor-syntax-namespace, var(--editor-syntax-type))",
  function: "var(--editor-syntax-function)",
  variable: "var(--editor-syntax-variable, var(--editor-text))",
  property: "var(--editor-syntax-property, var(--editor-text))",
  operator: "var(--editor-syntax-operator, var(--editor-text))",
  meta: "var(--editor-syntax-meta)",
  invalid: "var(--editor-syntax-invalid)",
} as const;

export type FileEditorSyntaxSlot = keyof typeof FILE_EDITOR_SYNTAX_COLORS;

const color = FILE_EDITOR_SYNTAX_COLORS;

// Comments stay upright: CJK fonts have no italic face, so browsers would slant the glyphs.
export const FILE_EDITOR_HIGHLIGHT_STYLE = HighlightStyle.define([
  { tag: tags.comment, color: color.comment },
  {
    tag: [tags.keyword, tags.modifier, tags.operatorKeyword, tags.definitionKeyword, tags.self, tags.null, tags.bool],
    color: color.keyword,
  },
  { tag: [tags.controlKeyword, tags.moduleKeyword], color: color.control },
  {
    tag: [tags.string, tags.special(tags.string), tags.character, tags.regexp, tags.attributeValue],
    color: color.string,
  },
  { tag: [tags.number, tags.unit], color: color.number },
  {
    tag: [
      tags.atom,
      tags.escape,
      tags.color,
      tags.labelName,
      tags.constant(tags.name),
      tags.constant(tags.variableName),
    ],
    color: color.constant,
  },
  { tag: [tags.typeName, tags.className, tags.tagName], color: color.type },
  { tag: tags.standard(tags.tagName), color: color.keyword },
  { tag: tags.namespace, color: color.namespace },
  {
    tag: [tags.variableName, tags.definition(tags.variableName), tags.local(tags.variableName)],
    color: color.variable,
  },
  {
    tag: [
      tags.propertyName,
      tags.definition(tags.propertyName),
      tags.special(tags.propertyName),
      tags.attributeName,
    ],
    color: color.property,
  },
  {
    tag: [
      tags.function(tags.variableName),
      tags.function(tags.propertyName),
      tags.function(tags.definition(tags.variableName)),
      tags.definition(tags.function(tags.variableName)),
    ],
    color: color.function,
  },
  { tag: [tags.operator, tags.angleBracket], color: color.operator },
  { tag: [tags.meta, tags.macroName, tags.special(tags.name)], color: color.meta },
  { tag: tags.heading, color: color.keyword, fontWeight: "600" },
  { tag: tags.strong, fontWeight: "600" },
  { tag: tags.emphasis, fontStyle: "italic" },
  { tag: tags.strikethrough, textDecoration: "line-through" },
  { tag: [tags.link, tags.url], color: color.string, textDecoration: "underline" },
  { tag: tags.monospace, color: color.constant },
  { tag: [tags.quote, tags.contentSeparator], color: color.comment },
  { tag: tags.invalid, color: color.invalid, textDecoration: "underline wavy" },
]);

export const FILE_EDITOR_SYNTAX_HIGHLIGHTING = syntaxHighlighting(FILE_EDITOR_HIGHLIGHT_STYLE);
