export type WaveformRadix = "binary" | "signed-decimal" | "unsigned-decimal" | "signed-hex" | "unsigned-hex";

export const WAVEFORM_RADIX_OPTIONS: Array<{ value: WaveformRadix; label: string }> = [
  { value: "binary", label: "二进制" },
  { value: "signed-decimal", label: "有符号十进制" },
  { value: "unsigned-decimal", label: "无符号十进制" },
  { value: "signed-hex", label: "有符号十六进制" },
  { value: "unsigned-hex", label: "无符号十六进制" },
];

export const DEFAULT_WAVEFORM_RADIX: WaveformRadix = "binary";

function normalizeBinaryValue(value: string, width: number) {
  const raw = value.trim().toLowerCase();
  if (raw.startsWith("0x")) {
    return { numeric: false as const, text: value };
  }
  const withoutPrefix = raw.startsWith("0b") ? raw.slice(2) : raw;
  if (!/^[01xz]+$/.test(withoutPrefix)) {
    return { numeric: false as const, text: value };
  }
  const safeWidth = Math.max(1, width);
  const padded = withoutPrefix.padStart(safeWidth, "0").slice(-safeWidth);
  if (/[xz]/.test(padded)) {
    return { numeric: false as const, text: padded };
  }
  return { numeric: true as const, text: padded };
}

function unsignedValue(binary: string) {
  return BigInt(`0b${binary}`);
}

function signedValue(binary: string, width: number) {
  const unsigned = unsignedValue(binary);
  const signBit = 1n << BigInt(Math.max(0, width - 1));
  const fullRange = 1n << BigInt(width);
  return (unsigned & signBit) === 0n ? unsigned : unsigned - fullRange;
}

function formatHex(value: bigint) {
  const prefix = value < 0n ? "-0x" : "0x";
  const magnitude = value < 0n ? -value : value;
  return `${prefix}${magnitude.toString(16)}`;
}

export function formatWaveformValue(value: string, width: number, radix: WaveformRadix) {
  const normalized = normalizeBinaryValue(value, width);
  if (!normalized.numeric) {
    return normalized.text;
  }
  if (radix === "binary") {
    return normalized.text;
  }
  if (radix === "unsigned-decimal") {
    return unsignedValue(normalized.text).toString(10);
  }
  if (radix === "signed-decimal") {
    return signedValue(normalized.text, normalized.text.length).toString(10);
  }
  if (radix === "unsigned-hex") {
    return formatHex(unsignedValue(normalized.text));
  }
  return formatHex(signedValue(normalized.text, normalized.text.length));
}
