import type {
  CodeCompletionItem,
  CodeDiagnostic,
  CodeDiagnosticSeverity,
  CodeDocumentSymbol,
  CodeHoverContent,
  CodeIntelligenceKind,
  CodeIntelligenceResult,
  CodeLocation,
  CodePosition,
  CodeRange,
  CodeReferenceLocation,
  LanguageServerConfiguration,
} from "./types";

type RawRecord = Record<string, unknown>;

function isRecord(value: unknown): value is RawRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : value === null || value === undefined ? "" : String(value);
}

function pick(raw: RawRecord, snake: string, camel: string): unknown {
  return raw[snake] ?? raw[camel];
}

function mapPosition(raw: unknown): CodePosition {
  const value = isRecord(raw) ? raw : {};
  return {
    line: Math.max(1, Math.trunc(Number(value.line)) || 1),
    column: Math.max(1, Math.trunc(Number(value.column)) || 1),
  };
}

export function mapCodeRange(raw: unknown): CodeRange {
  const value = isRecord(raw) ? raw : {};
  return { start: mapPosition(value.start), end: mapPosition(value.end) };
}

export function mapCodeLocation(raw: unknown): CodeLocation {
  const item = isRecord(raw) ? raw : {};
  const targetType = pick(item, "target_type", "targetType") === "external" ? "external" : "workspace";
  const rawDisplayPath = asString(pick(item, "display_path", "displayPath"));
  const path = asString(item.path) || rawDisplayPath;
  const displayPath = rawDisplayPath || path;
  const sourceId = asString(pick(item, "source_id", "sourceId"));
  return {
    targetType,
    ...(path ? { path } : {}),
    ...(targetType === "external" && displayPath ? { displayPath } : {}),
    ...(sourceId ? { sourceId } : {}),
    provider: asString(item.provider) || "unknown",
    range: mapCodeRange(item.range),
    selectionRange: mapCodeRange(pick(item, "selection_range", "selectionRange")),
  };
}

function mapHoverContents(raw: unknown): CodeHoverContent[] {
  return asArray(raw).flatMap((entry) => {
    if (!isRecord(entry)) return [];
    const value = asString(entry.value);
    if (!value.trim()) return [];
    return [{ kind: entry.kind === "markdown" ? "markdown" as const : "plaintext" as const, value }];
  });
}

function mapSymbols(raw: unknown, depth = 0): CodeDocumentSymbol[] {
  if (depth > 32) return [];
  // Some servers list symbols alphabetically; an outline reads in source order.
  return asArray(raw).flatMap((entry) => {
    if (!isRecord(entry)) return [];
    const name = asString(entry.name);
    if (!name) return [];
    const containerName = asString(pick(entry, "container_name", "containerName"));
    return [{
      name,
      detail: asString(entry.detail),
      kind: asString(entry.kind) || "variable",
      range: mapCodeRange(entry.range),
      selectionRange: mapCodeRange(pick(entry, "selection_range", "selectionRange")),
      ...(containerName ? { containerName } : {}),
      children: mapSymbols(entry.children, depth + 1),
    }];
  }).sort((left, right) => (
    left.range.start.line - right.range.start.line || left.range.start.column - right.range.start.column
  ));
}

function mapCompletionItems(raw: unknown): CodeCompletionItem[] {
  return asArray(raw).flatMap((entry) => {
    if (!isRecord(entry)) return [];
    const label = asString(entry.label);
    if (!label) return [];
    const rawEdit = pick(entry, "text_edit", "textEdit");
    return [{
      label,
      kind: asString(entry.kind) || "text",
      detail: asString(entry.detail),
      documentation: asString(entry.documentation),
      insertText: asString(pick(entry, "insert_text", "insertText")) || label,
      filterText: asString(pick(entry, "filter_text", "filterText")),
      sortText: asString(pick(entry, "sort_text", "sortText")),
      textEdit: isRecord(rawEdit)
        ? { range: mapCodeRange(rawEdit.range), newText: asString(pick(rawEdit, "new_text", "newText")) }
        : null,
      deprecated: entry.deprecated === true,
    }];
  });
}

function mapSeverity(raw: unknown): CodeDiagnosticSeverity {
  return raw === "error" || raw === "warning" || raw === "info" || raw === "hint" ? raw : "info";
}

function mapDiagnostics(raw: unknown): CodeDiagnostic[] {
  return asArray(raw).flatMap((entry) => {
    if (!isRecord(entry)) return [];
    const message = asString(entry.message);
    if (!message) return [];
    return [{
      range: mapCodeRange(entry.range),
      severity: mapSeverity(entry.severity),
      message,
      source: asString(entry.source),
      code: asString(entry.code),
    }];
  });
}

function mapTokens(raw: unknown): number[] {
  const values = asArray(raw);
  const usable = values.length - (values.length % 5);
  const tokens = new Array<number>(usable);
  for (let index = 0; index < usable; index += 1) {
    const value = Number(values[index]);
    tokens[index] = Number.isFinite(value) ? Math.trunc(value) : 0;
  }
  return tokens;
}

function mapVersion(raw: unknown): number | null {
  return typeof raw === "number" && Number.isFinite(raw) ? Math.trunc(raw) : null;
}

export function emptyCodeIntelligenceResult(
  kind: CodeIntelligenceKind,
  requestId: string,
  overrides: Partial<CodeIntelligenceResult> = {},
): CodeIntelligenceResult {
  return {
    requestId,
    kind,
    provider: "",
    available: false,
    supported: false,
    message: "",
    truncated: false,
    hover: { contents: [], range: null },
    references: [],
    symbols: [],
    semanticTokens: { legend: { types: [], modifiers: [] }, tokens: [], inactiveRanges: [], version: null },
    completion: { items: [], isIncomplete: false },
    diagnostics: { items: [], version: null, ready: false },
    ...overrides,
  };
}

/** Normalizes the backend's per-kind payload into one shape with empty defaults. */
export function mapCodeIntelligenceResult(
  raw: unknown,
  kind: CodeIntelligenceKind,
  requestId: string,
): CodeIntelligenceResult {
  const data = isRecord(raw) ? raw : {};
  const result = emptyCodeIntelligenceResult(kind, asString(pick(data, "request_id", "requestId")) || requestId, {
    provider: asString(data.provider),
    available: data.available !== false,
    supported: data.supported !== false,
    message: asString(data.message),
    truncated: data.truncated === true,
  });
  if (kind === "hover") {
    result.hover = {
      contents: mapHoverContents(data.contents),
      range: isRecord(data.range) ? mapCodeRange(data.range) : null,
    };
  } else if (kind === "references") {
    result.references = asArray(data.items).map<CodeReferenceLocation>((item) => ({
      ...mapCodeLocation(item),
      preview: isRecord(item) ? asString(item.preview) : "",
    }));
  } else if (kind === "documentSymbols") {
    result.symbols = mapSymbols(data.items);
  } else if (kind === "semanticTokens") {
    const legend = isRecord(data.legend) ? data.legend : {};
    result.semanticTokens = {
      legend: {
        types: asArray(legend.types).map(asString),
        modifiers: asArray(legend.modifiers).map(asString),
      },
      tokens: mapTokens(data.tokens),
      inactiveRanges: asArray(pick(data, "inactive_ranges", "inactiveRanges")).flatMap((entry) => {
        if (!isRecord(entry)) return [];
        const startLine = Math.trunc(Number(pick(entry, "start_line", "startLine")));
        const endLine = Math.trunc(Number(pick(entry, "end_line", "endLine")));
        return startLine >= 1 && endLine >= startLine ? [{ startLine, endLine }] : [];
      }),
      version: mapVersion(data.version),
    };
  } else if (kind === "completion") {
    result.completion = {
      items: mapCompletionItems(data.items),
      isIncomplete: pick(data, "is_incomplete", "isIncomplete") === true,
    };
  } else {
    result.diagnostics = {
      items: mapDiagnostics(data.items),
      version: mapVersion(data.version),
      ready: data.ready === true,
    };
  }
  return result;
}

export function mapLanguageServerConfiguration(raw: unknown): LanguageServerConfiguration | undefined {
  if (!isRecord(raw)) return undefined;
  const mode = raw.mode;
  if (mode !== "compile_commands" && mode !== "project_config" && mode !== "fallback") return undefined;
  return { mode, summary: asString(raw.summary), hint: asString(raw.hint) };
}
