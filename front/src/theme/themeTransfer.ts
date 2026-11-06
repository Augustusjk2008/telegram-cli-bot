import { normalizeChatTypography } from "./chatTypography";
import { normalizeThemeMaterial } from "./material";
import { normalizeIllustrations } from "./resolveAppearance";
import type { PortableTheme, ThemeDocument, ThemeIllustrationAssetImport, UiTheme } from "./types";

const ZIP_LOCAL = 0x04034b50;
const ZIP_CENTRAL = 0x02014b50;
const ZIP_END = 0x06054b50;

export type ReadThemeFileResult = unknown | { document: unknown; assets: ThemeIllustrationAssetImport[] };

function extensionForMime(mimeType: string) {
  return mimeType === "image/png" ? "png" : mimeType === "image/jpeg" ? "jpg" : "webp";
}
function bytesFromBase64(value: string) {
  const payload = value.replace(/^data:[^,]+,/, "");
  const binary = atob(payload);
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
}

function base64FromBytes(bytes: Uint8Array) {
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

function crc32(bytes: Uint8Array) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function writeU16(view: DataView, offset: number, value: number) { view.setUint16(offset, value, true); }
function writeU32(view: DataView, offset: number, value: number) { view.setUint32(offset, value, true); }

function zipStored(entries: Array<{ name: string; data: Uint8Array }>) {
  const encoder = new TextEncoder();
  const local: Uint8Array[] = [];
  const central: Uint8Array[] = [];
  let offset = 0;
  for (const entry of entries) {
    const name = encoder.encode(entry.name);
    const header = new Uint8Array(30 + name.length);
    const view = new DataView(header.buffer);
    writeU32(view, 0, ZIP_LOCAL);
    writeU16(view, 4, 20);
    writeU16(view, 6, 0);
    writeU16(view, 8, 0);
    writeU16(view, 10, 0);
    writeU16(view, 12, 0);
    writeU32(view, 14, crc32(entry.data));
    writeU32(view, 18, entry.data.length);
    writeU32(view, 22, entry.data.length);
    writeU16(view, 26, name.length);
    writeU16(view, 28, 0);
    header.set(name, 30);
    local.push(header, entry.data);

    const record = new Uint8Array(46 + name.length);
    const centralView = new DataView(record.buffer);
    writeU32(centralView, 0, ZIP_CENTRAL);
    writeU16(centralView, 4, 20);
    writeU16(centralView, 6, 20);
    writeU16(centralView, 8, 0);
    writeU16(centralView, 10, 0);
    writeU16(centralView, 12, 0);
    writeU16(centralView, 14, 0);
    writeU32(centralView, 16, crc32(entry.data));
    writeU32(centralView, 20, entry.data.length);
    writeU32(centralView, 24, entry.data.length);
    writeU16(centralView, 28, name.length);
    writeU16(centralView, 30, 0);
    writeU16(centralView, 32, 0);
    writeU16(centralView, 34, 0);
    writeU16(centralView, 36, 0);
    writeU32(centralView, 38, 0);
    writeU32(centralView, 42, offset);
    record.set(name, 46);
    central.push(record);
    offset += header.length + entry.data.length;
  }
  const centralSize = central.reduce((sum, value) => sum + value.length, 0);
  const end = new Uint8Array(22);
  const endView = new DataView(end.buffer);
  writeU32(endView, 0, ZIP_END);
  writeU16(endView, 4, 0);
  writeU16(endView, 6, 0);
  writeU16(endView, 8, entries.length);
  writeU16(endView, 10, entries.length);
  writeU32(endView, 12, centralSize);
  writeU32(endView, 16, offset);
  writeU16(endView, 20, 0);
  return new Blob([...local, ...central, end], { type: "application/zip" });
}

function findEnd(bytes: Uint8Array) {
  for (let offset = bytes.length - 22; offset >= Math.max(0, bytes.length - 65557); offset -= 1) {
    if (new DataView(bytes.buffer, bytes.byteOffset + offset, 4).getUint32(0, true) === ZIP_END) return offset;
  }
  return -1;
}

async function unzipStored(bytes: Uint8Array) {
  const end = findEnd(bytes);
  if (end < 0) throw new Error("主题 ZIP 缺少目录");
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const count = view.getUint16(end + 8, true);
  const centralOffset = view.getUint32(end + 16, true);
  const entries = new Map<string, Uint8Array>();
  let cursor = centralOffset;
  const decoder = new TextDecoder();
  for (let index = 0; index < count; index += 1) {
    if (view.getUint32(cursor, true) !== ZIP_CENTRAL) throw new Error("主题 ZIP 目录无效");
    const method = view.getUint16(cursor + 10, true);
    const compressedSize = view.getUint32(cursor + 20, true);
    const nameLength = view.getUint16(cursor + 28, true);
    const extraLength = view.getUint16(cursor + 30, true);
    const commentLength = view.getUint16(cursor + 32, true);
    const name = decoder.decode(bytes.subarray(cursor + 46, cursor + 46 + nameLength));
    const localOffset = view.getUint32(cursor + 42, true);
    if (method !== 0) throw new Error("主题 ZIP 使用了暂不支持的压缩方式");
    if (view.getUint32(localOffset, true) !== ZIP_LOCAL) throw new Error("主题 ZIP 文件项无效");
    const localNameLength = view.getUint16(localOffset + 26, true);
    const localExtraLength = view.getUint16(localOffset + 28, true);
    const dataStart = localOffset + 30 + localNameLength + localExtraLength;
    entries.set(name, bytes.slice(dataStart, dataStart + compressedSize));
    cursor += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

export function portableTheme(theme: UiTheme): PortableTheme {
  return {
    schemaVersion: 1,
    name: theme.name,
    baseId: theme.baseId,
    appearance: {
      colors: { ...theme.appearance.colors, overrides: { ...theme.appearance.colors.overrides } },
      typography: normalizeChatTypography(theme.appearance.typography),
      material: normalizeThemeMaterial(theme.appearance.material),
      illustrations: normalizeIllustrations(theme.appearance.illustrations),
    },
  };
}

function normalizeImportedTheme(value: unknown): unknown {
  if (!value || typeof value !== "object" || Array.isArray(value)) return value;
  const theme = value as Record<string, unknown>;
  const appearance = theme.appearance;
  if (!appearance || typeof appearance !== "object" || Array.isArray(appearance)) return value;
  const source = appearance as Record<string, unknown>;
  const legacyIllustrations = source.illustrations;
  const preserveLegacyIllustrations = Boolean(
    legacyIllustrations && typeof legacyIllustrations === "object" && !Array.isArray(legacyIllustrations)
      && "setId" in legacyIllustrations,
  );
  return {
    ...theme,
    appearance: {
      ...source,
      illustrations: preserveLegacyIllustrations
        ? legacyIllustrations
        : normalizeIllustrations(source.illustrations),
    },
  };
}

export function normalizeThemeDocument(value: unknown): unknown {
  if (!value || typeof value !== "object" || Array.isArray(value)) return value;
  const document = value as Record<string, unknown>;
  if (Array.isArray(document.themes)) {
    return { ...document, themes: document.themes.map(normalizeImportedTheme) };
  }
  return normalizeImportedTheme(value);
}

export async function readThemeFile(file: File): Promise<ReadThemeFileResult> {
  try {
    const bytes = typeof file.arrayBuffer === "function" ? new Uint8Array(await file.arrayBuffer()) : null;
    if (bytes && bytes.length >= 4 && bytes[0] === 0x50 && bytes[1] === 0x4b && bytes[2] === 0x03 && bytes[3] === 0x04) {
      const entries = await unzipStored(bytes);
      const json = entries.get("theme.json");
      if (!json) throw new Error("主题 ZIP 缺少 theme.json");
      const document = normalizeThemeDocument(JSON.parse(new TextDecoder().decode(json).replace(/^\uFEFF/, "")));
      const assets: ThemeIllustrationAssetImport[] = [];
      for (const [name, data] of entries) {
        const match = /^assets\/([A-Za-z0-9][A-Za-z0-9._-]{0,159})\.(png|jpg|jpeg|webp)$/i.exec(name);
        if (!match) continue;
        const mimeType = match[2].toLowerCase() === "png" ? "image/png" : match[2].toLowerCase() === "webp" ? "image/webp" : "image/jpeg";
        assets.push({ assetId: match[1], mimeType, data: `data:${mimeType};base64,${base64FromBytes(data)}` });
      }
      return { document, assets };
    }
    const text = bytes && bytes.length ? new TextDecoder().decode(bytes) : await file.text();
    return normalizeThemeDocument(JSON.parse(text.replace(/^\uFEFF/, "")));
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new Error("JSON 文件格式无效，请检查后重试。");
    }
    throw error instanceof Error ? error : new Error("主题文件格式无效，请检查后重试。");
  }
}

export async function downloadThemeDocument(
  value: ThemeDocument,
  name: string,
  assets: Array<{ assetId: string; mimeType: string; data: Uint8Array | ArrayBuffer }> = [],
) {
  const filenameBase = `orbit-theme-${name.replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_").slice(0, 80)}`;
  let blob: Blob;
  let filename: string;
  if (assets.length) {
    const themeJson = new TextEncoder().encode(JSON.stringify(value, null, 2) + "\n");
    const entries = [
      { name: "theme.json", data: themeJson },
      ...assets.map((asset) => ({
        name: `assets/${asset.assetId}.${extensionForMime(asset.mimeType)}`,
        data: asset.data instanceof Uint8Array ? asset.data : new Uint8Array(asset.data),
      })),
    ];
    blob = zipStored(entries);
    filename = `${filenameBase}.zip`;
  } else {
    blob = new Blob([JSON.stringify(value, null, 2) + "\n"], { type: "application/json;charset=utf-8" });
    filename = `${filenameBase}.json`;
  }
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  try { link.click(); }
  finally {
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
