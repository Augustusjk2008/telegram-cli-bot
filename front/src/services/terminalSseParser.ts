export type TerminalSseEvent = {
  event: string;
  id: string;
  data: string;
};

export class TerminalSseParser {
  private readonly decoder = new TextDecoder();
  private buffer = "";

  constructor(private readonly onEvent: (event: TerminalSseEvent) => void) {}

  push(chunk: Uint8Array) {
    this.buffer += this.decoder.decode(chunk, { stream: true });
    this.drain(false);
  }

  finish() {
    this.buffer += this.decoder.decode();
    this.drain(true);
  }

  private drain(final: boolean) {
    const normalized = this.buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    const frames = normalized.split("\n\n");
    this.buffer = final ? "" : frames.pop() || "";
    for (const frame of frames) {
      if (!frame.trim()) continue;
      let event = "message";
      let id = "";
      const data: string[] = [];
      for (const line of frame.split("\n")) {
        if (!line || line.startsWith(":")) continue;
        const colon = line.indexOf(":");
        const field = colon < 0 ? line : line.slice(0, colon);
        let value = colon < 0 ? "" : line.slice(colon + 1);
        if (value.startsWith(" ")) value = value.slice(1);
        if (field === "event") event = value || "message";
        else if (field === "id") id = value;
        else if (field === "data") data.push(value);
      }
      if (data.length > 0) this.onEvent({ event, id, data: data.join("\n") });
    }
  }
}
