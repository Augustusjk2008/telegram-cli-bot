import { describe, expect, it } from "vitest";
import { TerminalSseParser } from "../services/terminalSseParser";

describe("TerminalSseParser", () => {
  it("parses CRLF, split UTF-8 chunks, multiline data, and a final unterminated event", () => {
    const events: Array<{ event: string; id: string; data: string }> = [];
    const parser = new TerminalSseParser((event) => events.push(event));
    const bytes = new TextEncoder().encode("event: output\r\nid: 7\r\ndata: {\"data\":\"ä½ \r\ndata: å¥½\"}\r\n\r\nevent: ready\ndata: {}\n");

    parser.push(bytes.slice(0, 37));
    parser.push(bytes.slice(37, 42));
    parser.push(bytes.slice(42));
    parser.finish();

    expect(events).toEqual([
      { event: "output", id: "7", data: "{\"data\":\"ä½ \nå¥½\"}" },
      { event: "ready", id: "", data: "{}" },
    ]);
  });

  it("keeps legacy data-only events compatible", () => {
    const events: Array<{ event: string; id: string; data: string }> = [];
    const parser = new TerminalSseParser((event) => events.push(event));
    parser.push(new TextEncoder().encode("data: {\"data\":\"YQ==\"}\n\n"));
    parser.finish();

    expect(events).toEqual([{ event: "message", id: "", data: "{\"data\":\"YQ==\"}" }]);
  });
});
