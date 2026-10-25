import { normalizeChatTypography } from "./chatTypography";
import type { PortableTheme, ThemeDocument, UiTheme } from "./types";

export function portableTheme(theme: UiTheme): PortableTheme {
  return {
    schemaVersion: 1,
    name: theme.name,
    baseId: theme.baseId,
    appearance: {
      colors: { ...theme.appearance.colors, overrides: { ...theme.appearance.colors.overrides } },
      typography: normalizeChatTypography(theme.appearance.typography),
    },
  };
}

export async function readThemeFile(file: File): Promise<unknown> {
  let text: string;
  try { text = await file.text(); }
  catch { throw new Error("无法读取主题文件，请重新选择文件。"); }
  try { return JSON.parse(text.replace(/^\uFEFF/, "")); }
  catch { throw new Error("JSON 文件格式无效，请检查后重试。"); }
}

export function downloadThemeDocument(value: ThemeDocument, name: string) {
  const filename = `orbit-theme-${name.replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_").slice(0, 80)}.json`;
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2) + "\n"], { type: "application/json;charset=utf-8" }));
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
