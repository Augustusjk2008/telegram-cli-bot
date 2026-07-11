import { describe, expect, it } from "vitest";
import {
  decodeTerminalV2Frame,
  TERMINAL_V2_HEADER_BYTES,
  TerminalConnectionGeneration,
  TerminalRecoveryTracker,
} from "../terminal/terminalRecovery";

function frame(sequence: bigint, payload: string, flags = 0) {
  const bytes = new TextEncoder().encode(payload);
  const buffer = new ArrayBuffer(TERMINAL_V2_HEADER_BYTES + bytes.length);
  const view = new DataView(buffer);
  [0x54, 0x43, 0x42, 0x32].forEach((value, index) => view.setUint8(index, value));
  view.setUint8(4, 2);
  view.setUint8(5, flags);
  view.setBigUint64(6, sequence, false);
  new Uint8Array(buffer, TERMINAL_V2_HEADER_BYTES).set(bytes);
  return buffer;
}

describe("terminal v2 recovery", () => {
  it("decodes the backend TCB2 header and uint64 sequence", () => {
    const decoded = decodeTerminalV2Frame(frame(42n, "hello"));

    expect(decoded?.sequence).toBe(42);
    expect(decoded?.flags).toBe(0);
    expect(new TextDecoder().decode(decoded?.payload)).toBe("hello");
  });

  it("ignores duplicates, detects gaps, and resets on a new stream", () => {
    const tracker = new TerminalRecoveryTracker();
    tracker.beginStream("stream-a");

    expect(tracker.accept(1)).toMatchObject({ duplicate: false, gap: false });
    expect(tracker.accept(1)).toMatchObject({ duplicate: true, gap: false });
    expect(tracker.accept(3)).toMatchObject({ duplicate: false, gap: true, replayRequired: true, previous: 1 });
    expect(tracker.getSnapshot().lastAppliedSequence).toBe(1);
    expect(tracker.beginStream("stream-b")).toMatchObject({ changed: true });
    expect(tracker.getSnapshot()).toEqual({ streamId: "stream-b", lastAppliedSequence: 0 });
  });

  it("advances to the declared gap tail before replay continues", () => {
    const tracker = new TerminalRecoveryTracker(10);
    tracker.beginStream("stream-a");
    tracker.applyGap("stream-a", 14);

    expect(tracker.accept(15)).toMatchObject({ duplicate: false, gap: false });
    expect(tracker.getSnapshot().lastAppliedSequence).toBe(15);
  });

  it("does not apply an old Blob after a newer connection generation starts", async () => {
    const generations = new TerminalConnectionGeneration();
    const writes: string[] = [];
    let release!: (buffer: ArrayBuffer) => void;
    const oldBlobRead = new Promise<ArrayBuffer>((resolve) => {
      release = resolve;
    });
    const oldGeneration = generations.next();
    const pending = oldBlobRead.then((buffer) => {
      if (generations.isCurrent(oldGeneration)) {
        writes.push(new TextDecoder().decode(buffer));
      }
    });

    generations.next();
    release(new TextEncoder().encode("stale").buffer as ArrayBuffer);
    await pending;

    expect(writes).toEqual([]);
  });
});
