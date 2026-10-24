import type {
  ChatBodyFontFamilyName,
  ChatBodyFontSizeName,
  ChatBodyLineHeightName,
  ChatBodyParagraphSpacingName,
  ChatTypography,
} from "./types";

export const DEFAULT_CHAT_BODY_FONT_FAMILY: ChatBodyFontFamilyName = "sans";
export const DEFAULT_CHAT_BODY_FONT_SIZE: ChatBodyFontSizeName = "medium";
export const DEFAULT_CHAT_BODY_LINE_HEIGHT: ChatBodyLineHeightName = "normal";
export const DEFAULT_CHAT_BODY_PARAGRAPH_SPACING: ChatBodyParagraphSpacingName = "normal";

export const DEFAULT_CHAT_TYPOGRAPHY: ChatTypography = {
  chatBodyFontFamily: DEFAULT_CHAT_BODY_FONT_FAMILY,
  chatBodyFontSize: DEFAULT_CHAT_BODY_FONT_SIZE,
  chatBodyLineHeight: DEFAULT_CHAT_BODY_LINE_HEIGHT,
  chatBodyParagraphSpacing: DEFAULT_CHAT_BODY_PARAGRAPH_SPACING,
};

export const CHAT_BODY_FONT_FAMILY_OPTIONS: Array<{
  value: ChatBodyFontFamilyName;
  label: string;
}> = [
  { value: "sans", label: "系统默认" },
  { value: "serif", label: "宋体阅读" },
  { value: "kai", label: "楷体阅读" },
  { value: "fangsong", label: "仿宋阅读" },
  { value: "mono", label: "代码字体" },
];

export const CHAT_BODY_FONT_SIZE_OPTIONS: Array<{
  value: ChatBodyFontSizeName;
  label: string;
}> = [
  { value: "small", label: "小" },
  { value: "medium", label: "中" },
  { value: "large", label: "大" },
];

export const CHAT_BODY_LINE_HEIGHT_OPTIONS: Array<{
  value: ChatBodyLineHeightName;
  label: string;
}> = [
  { value: "tight", label: "紧凑" },
  { value: "normal", label: "标准" },
  { value: "relaxed", label: "宽松" },
];

export const CHAT_BODY_PARAGRAPH_SPACING_OPTIONS: Array<{
  value: ChatBodyParagraphSpacingName;
  label: string;
}> = [
  { value: "tight", label: "紧凑" },
  { value: "normal", label: "标准" },
  { value: "relaxed", label: "宽松" },
];

function isChatBodyFontFamilyName(value: unknown): value is ChatBodyFontFamilyName {
  return value === "sans" || value === "serif" || value === "kai" || value === "fangsong" || value === "mono";
}

function isChatBodyFontSizeName(value: unknown): value is ChatBodyFontSizeName {
  return value === "small" || value === "medium" || value === "large";
}

function isChatBodyLineHeightName(value: unknown): value is ChatBodyLineHeightName {
  return value === "tight" || value === "normal" || value === "relaxed";
}

function isChatBodyParagraphSpacingName(value: unknown): value is ChatBodyParagraphSpacingName {
  return value === "tight" || value === "normal" || value === "relaxed";
}

export function isChatTypography(value: unknown): value is ChatTypography {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return Object.keys(record).length === 4
    && isChatBodyFontFamilyName(record.chatBodyFontFamily)
    && isChatBodyFontSizeName(record.chatBodyFontSize)
    && isChatBodyLineHeightName(record.chatBodyLineHeight)
    && isChatBodyParagraphSpacingName(record.chatBodyParagraphSpacing);
}

export function normalizeChatTypography(value: unknown): ChatTypography {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return { ...DEFAULT_CHAT_TYPOGRAPHY };
  }
  const record = value as Record<string, unknown>;
  return {
    chatBodyFontFamily: isChatBodyFontFamilyName(record.chatBodyFontFamily)
      ? record.chatBodyFontFamily
      : DEFAULT_CHAT_BODY_FONT_FAMILY,
    chatBodyFontSize: isChatBodyFontSizeName(record.chatBodyFontSize)
      ? record.chatBodyFontSize
      : DEFAULT_CHAT_BODY_FONT_SIZE,
    chatBodyLineHeight: isChatBodyLineHeightName(record.chatBodyLineHeight)
      ? record.chatBodyLineHeight
      : DEFAULT_CHAT_BODY_LINE_HEIGHT,
    chatBodyParagraphSpacing: isChatBodyParagraphSpacingName(record.chatBodyParagraphSpacing)
      ? record.chatBodyParagraphSpacing
      : DEFAULT_CHAT_BODY_PARAGRAPH_SPACING,
  };
}

export function getChatBodyFontFamilyValue(fontFamily: ChatBodyFontFamilyName) {
  if (fontFamily === "kai") return '"KaiTi", "Kaiti SC", "STKaiti", serif';
  if (fontFamily === "fangsong") return '"FangSong", "STFangsong", serif';
  if (fontFamily === "serif") return '"SimSun", "Songti SC", "STSong", serif';
  if (fontFamily === "mono") return '"Cascadia Code", "Consolas", "Microsoft YaHei UI", monospace';
  return '"Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif';
}

export function getChatBodyFontSizeValue(fontSize: ChatBodyFontSizeName) {
  if (fontSize === "small") return "14px";
  if (fontSize === "large") return "17px";
  return "15px";
}

export function getChatBodyLineHeightValue(lineHeight: ChatBodyLineHeightName) {
  if (lineHeight === "tight") return "1.65";
  if (lineHeight === "relaxed") return "2.1";
  return "1.9";
}

export function getChatBodyParagraphSpacingValue(paragraphSpacing: ChatBodyParagraphSpacingName) {
  if (paragraphSpacing === "tight") return "0.45em";
  if (paragraphSpacing === "relaxed") return "1.1em";
  return "0.75em";
}

export function chatTypographyCssVariables(typography: ChatTypography): Record<string, string> {
  return {
    "--chat-body-font-family": getChatBodyFontFamilyValue(typography.chatBodyFontFamily),
    "--chat-body-font-size": getChatBodyFontSizeValue(typography.chatBodyFontSize),
    "--chat-body-line-height": getChatBodyLineHeightValue(typography.chatBodyLineHeight),
    "--chat-body-paragraph-spacing": getChatBodyParagraphSpacingValue(typography.chatBodyParagraphSpacing),
  };
}
