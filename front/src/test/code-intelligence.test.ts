import { describe, expect, it } from "vitest";
import { mapCodeIntelligenceResult, mapLanguageServerConfiguration } from "../services/codeIntelligenceMapping";
import type { CodeDocumentSymbol } from "../services/types";
import { rankTextFallbackLocations } from "../workbench/codeNavigationTextFallback";
import { findDocumentSymbolPath } from "../workbench/useDocumentSymbols";

describe("code intelligence response mapping", () => {
  it("maps the backend's snake_case payloads", () => {
    const tokens = mapCodeIntelligenceResult({
      request_id: "r1",
      provider: "clangd",
      available: true,
      supported: true,
      legend: { types: ["variable"], modifiers: ["readonly"] },
      // A trailing partial token must not shift the five-integer groups.
      tokens: [1, 1, 3, 0, 1, 2, 2],
      inactive_ranges: [{ start_line: 4, end_line: 6 }, { start_line: 9, end_line: 2 }],
      version: 7,
    }, "semanticTokens", "fallback");
    expect(tokens.requestId).toBe("r1");
    expect(tokens.semanticTokens).toEqual({
      legend: { types: ["variable"], modifiers: ["readonly"] },
      tokens: [1, 1, 3, 0, 1],
      inactiveRanges: [{ startLine: 4, endLine: 6 }],
      version: 7,
    });

    const references = mapCodeIntelligenceResult({
      items: [{
        target_type: "workspace",
        path: "src/a.cpp",
        provider: "clangd",
        range: { start: { line: 3, column: 5 }, end: { line: 3, column: 9 } },
        selection_range: { start: { line: 3, column: 5 }, end: { line: 3, column: 9 } },
        preview: "auto x = read();",
      }],
      truncated: true,
    }, "references", "r2");
    expect(references.truncated).toBe(true);
    expect(references.references[0]).toMatchObject({
      targetType: "workspace",
      path: "src/a.cpp",
      preview: "auto x = read();",
      selectionRange: { start: { line: 3, column: 5 } },
    });

    const diagnostics = mapCodeIntelligenceResult({
      items: [{ range: {}, severity: "fatal", message: "boom", source: "clang", code: 12 }],
      ready: true,
      version: 3,
    }, "diagnostics", "r3");
    expect(diagnostics.diagnostics).toEqual({
      items: [{
        range: { start: { line: 1, column: 1 }, end: { line: 1, column: 1 } },
        severity: "info",
        message: "boom",
        source: "clang",
        code: "12",
      }],
      version: 3,
      ready: true,
    });
  });

  it("reports an unavailable service as empty data", () => {
    const result = mapCodeIntelligenceResult({ available: false, supported: false }, "hover", "r4");
    expect(result).toMatchObject({ requestId: "r4", available: false, supported: false });
    expect(result.hover.contents).toEqual([]);
  });

  it("accepts only known build-configuration modes", () => {
    expect(mapLanguageServerConfiguration({ mode: "fallback", summary: "默认参数", hint: "提示" }))
      .toEqual({ mode: "fallback", summary: "默认参数", hint: "提示" });
    expect(mapLanguageServerConfiguration({ mode: "other" })).toBeUndefined();
  });
});

describe("text fallback for code navigation", () => {
  it("keeps whole-word hits and puts declarations first", () => {
    const locations = rankTextFallbackLocations("receive", [
      { path: "src/use.cpp", line: 9, column: 12, preview: "  auto n = dev.receive(buffer);" },
      { path: "src/other.cpp", line: 2, column: 3, preview: "  receive_all();" },
      { path: "src/dev.cpp", line: 40, column: 27, preview: "Result<size_t> ComDevice::receive(Buffer b) {" },
      { path: "src/dev.h", line: 7, column: 9, preview: "#define receive(buffer) do_receive(buffer)" },
    ]);
    expect(locations.map((item) => `${item.path}:${item.selectionRange.start.line}`)).toEqual([
      "src/dev.h:7",
      "src/dev.cpp:40",
      "src/use.cpp:9",
    ]);
    expect(locations[0].provider).toBe("文本搜索");
    expect(rankTextFallbackLocations("->", [{ path: "a", line: 1, column: 1, preview: "a->b" }])).toEqual([]);
  });
});

describe("document symbol path", () => {
  it("returns the symbols enclosing the cursor, outermost first", () => {
    const symbol = (name: string, startLine: number, endLine: number, children: CodeDocumentSymbol[] = []): CodeDocumentSymbol => ({
      name,
      detail: "",
      kind: "function",
      range: { start: { line: startLine, column: 1 }, end: { line: endLine, column: 2 } },
      selectionRange: { start: { line: startLine, column: 1 }, end: { line: startLine, column: 5 } },
      children,
    });
    const symbols = [symbol("ns", 1, 30, [symbol("first", 2, 10), symbol("second", 12, 20)]), symbol("tail", 40, 50)];
    expect(findDocumentSymbolPath(symbols, { line: 15, column: 3 }).map((item) => item.name)).toEqual(["ns", "second"]);
    expect(findDocumentSymbolPath(symbols, { line: 35, column: 1 })).toEqual([]);
    expect(findDocumentSymbolPath(symbols, null)).toEqual([]);
  });
});
