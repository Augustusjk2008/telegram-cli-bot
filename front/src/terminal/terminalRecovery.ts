export const TERMINAL_PROTOCOL_VERSION = 2;
export const TERMINAL_V2_HEADER_BYTES = 14;

const TERMINAL_V2_MAGIC = [0x54, 0x43, 0x42, 0x32] as const;

export type TerminalV2Frame = {
  flags: number;
  sequence: number;
  payload: Uint8Array;
};

export type TerminalRecoverySnapshot = {
  streamId: string;
  lastAppliedSequence: number;
};

export class TerminalConnectionGeneration {
  private current = 0;

  next() {
    this.current += 1;
    return this.current;
  }

  isCurrent(generation: number) {
    return generation === this.current;
  }
}

export function decodeTerminalV2Frame(data: ArrayBuffer): TerminalV2Frame | null {
  if (data.byteLength < TERMINAL_V2_HEADER_BYTES) {
    return null;
  }
  const view = new DataView(data);
  if (TERMINAL_V2_MAGIC.some((byte, index) => view.getUint8(index) !== byte)) {
    return null;
  }
  if (view.getUint8(4) !== TERMINAL_PROTOCOL_VERSION) {
    return null;
  }
  const rawSequence = view.getBigUint64(6, false);
  if (rawSequence > BigInt(Number.MAX_SAFE_INTEGER)) {
    return null;
  }
  return {
    flags: view.getUint8(5),
    sequence: Number(rawSequence),
    payload: new Uint8Array(data.slice(TERMINAL_V2_HEADER_BYTES)),
  };
}

export class TerminalRecoveryTracker {
  private snapshot: TerminalRecoverySnapshot;

  constructor(initialSequence = 0) {
    this.snapshot = { streamId: "", lastAppliedSequence: Math.max(0, initialSequence) };
  }

  getSnapshot(): TerminalRecoverySnapshot {
    return { ...this.snapshot };
  }

  beginStream(streamId: string) {
    const normalized = String(streamId || "");
    const changed = Boolean(this.snapshot.streamId && normalized && this.snapshot.streamId !== normalized);
    if (changed) {
      this.snapshot.lastAppliedSequence = 0;
    }
    if (normalized) {
      this.snapshot.streamId = normalized;
    }
    return { changed, snapshot: this.getSnapshot() };
  }

  accept(sequence: number) {
    const normalized = Math.max(0, Math.floor(sequence));
    const previous = this.snapshot.lastAppliedSequence;
    if (normalized <= previous) {
      return { duplicate: true, gap: false, replayRequired: false, previous, snapshot: this.getSnapshot() };
    }
    const gap = previous > 0 && normalized !== previous + 1;
    if (!gap) {
      this.snapshot.lastAppliedSequence = normalized;
    }
    return { duplicate: false, gap, replayRequired: gap, previous, snapshot: this.getSnapshot() };
  }

  applyGap(streamId: string, gapTo: number) {
    const stream = this.beginStream(streamId);
    this.snapshot.lastAppliedSequence = Math.max(0, Math.floor(gapTo));
    return { streamChanged: stream.changed, snapshot: this.getSnapshot() };
  }
}
