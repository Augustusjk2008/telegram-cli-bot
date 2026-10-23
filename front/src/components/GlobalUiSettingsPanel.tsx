import { Bell } from "lucide-react";
import { useState } from "react";
import { ThemeDropdown } from "./ThemeDropdown";
import {
  CHAT_BODY_FONT_FAMILY_OPTIONS,
  CHAT_BODY_FONT_SIZE_OPTIONS,
  CHAT_BODY_LINE_HEIGHT_OPTIONS,
  CHAT_BODY_PARAGRAPH_SPACING_OPTIONS,
  DEFAULT_CHAT_BODY_FONT_FAMILY,
  DEFAULT_CHAT_BODY_FONT_SIZE,
  DEFAULT_CHAT_BODY_LINE_HEIGHT,
  DEFAULT_CHAT_BODY_PARAGRAPH_SPACING,
  DEFAULT_UI_THEME,
  type ChatBodyFontFamilyName,
  type ChatBodyFontSizeName,
  type ChatBodyLineHeightName,
  type ChatBodyParagraphSpacingName,
  type UiThemeName,
} from "../theme";
import {
  getBrowserNotificationPermission,
  readChatCompletionWebNotificationEnabled,
  requestBrowserNotificationPermission,
  writeChatCompletionWebNotificationEnabled,
} from "../utils/chatNotificationEvents";
import type { BrowserNotificationPermission } from "../services/types";

type Props = {
  canManage?: boolean;
  themeName?: UiThemeName;
  onThemeChange?: (themeName: UiThemeName) => void | Promise<void>;
  chatBodyFontFamily?: ChatBodyFontFamilyName;
  onChatBodyFontFamilyChange?: (value: ChatBodyFontFamilyName) => void;
  chatBodyFontSize?: ChatBodyFontSizeName;
  onChatBodyFontSizeChange?: (value: ChatBodyFontSizeName) => void;
  chatBodyLineHeight?: ChatBodyLineHeightName;
  onChatBodyLineHeightChange?: (value: ChatBodyLineHeightName) => void;
  chatBodyParagraphSpacing?: ChatBodyParagraphSpacingName;
  onChatBodyParagraphSpacingChange?: (value: ChatBodyParagraphSpacingName) => void;
  chatEnterToSend?: boolean;
  onChatEnterToSendChange?: (value: boolean) => void;
};

function permissionText(permission: BrowserNotificationPermission) {
  if (permission === "granted") return "已允许";
  if (permission === "denied") return "已拒绝";
  if (permission === "unsupported") return "浏览器不支持";
  return "未询问";
}

export function GlobalUiSettingsPanel({
  canManage = true,
  themeName = DEFAULT_UI_THEME,
  onThemeChange,
  chatBodyFontFamily = DEFAULT_CHAT_BODY_FONT_FAMILY,
  onChatBodyFontFamilyChange,
  chatBodyFontSize = DEFAULT_CHAT_BODY_FONT_SIZE,
  onChatBodyFontSizeChange,
  chatBodyLineHeight = DEFAULT_CHAT_BODY_LINE_HEIGHT,
  onChatBodyLineHeightChange,
  chatBodyParagraphSpacing = DEFAULT_CHAT_BODY_PARAGRAPH_SPACING,
  onChatBodyParagraphSpacingChange,
  chatEnterToSend = true,
  onChatEnterToSendChange,
}: Props) {
  const [notificationEnabled, setNotificationEnabled] = useState(() => readChatCompletionWebNotificationEnabled());
  const [notificationPermission, setNotificationPermission] = useState<BrowserNotificationPermission>(() => getBrowserNotificationPermission());
  const [requestingPermission, setRequestingPermission] = useState(false);
  const [notice, setNotice] = useState("");

  async function changeTheme(value: UiThemeName) {
    if (value === themeName || !onThemeChange) return;
    await onThemeChange(value);
    setNotice("全局主题已更新");
  }

  function changeNotification(value: boolean) {
    setNotificationEnabled(value);
    writeChatCompletionWebNotificationEnabled(value);
    setNotice(value ? "全局网页通知已开启" : "全局网页通知已关闭");
  }

  async function requestPermission() {
    setRequestingPermission(true);
    try {
      const next = await requestBrowserNotificationPermission();
      setNotificationPermission(next);
      if (next === "granted") changeNotification(true);
      else if (next === "denied") setNotice("浏览器已拒绝通知权限");
      else if (next === "unsupported") setNotice("当前浏览器不支持通知");
    } finally {
      setRequestingPermission(false);
    }
  }

  const selectClass = "w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)] disabled:opacity-60";

  return (
    <section aria-labelledby="global-ui-settings-title" className="space-y-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
      <div>
        <h2 id="global-ui-settings-title" className="text-base font-semibold text-[var(--text)]">通用显示设置</h2>
        <p className="mt-1 text-sm text-[var(--muted)]">全局配置 · 影响所有智能体和当前浏览器中的聊天界面。</p>
      </div>
      <fieldset disabled={!canManage} className="space-y-3">
        <ThemeDropdown value={themeName} onChange={(value) => void changeTheme(value)} />
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="space-y-2">
            <span className="text-sm font-medium text-[var(--text)]">聊天正文字体</span>
            <select aria-label="聊天正文字体" value={chatBodyFontFamily} onChange={(event) => onChatBodyFontFamilyChange?.(event.target.value as ChatBodyFontFamilyName)} className={selectClass}>
              {CHAT_BODY_FONT_FAMILY_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium text-[var(--text)]">聊天行间距</span>
            <select aria-label="聊天行间距" value={chatBodyLineHeight} onChange={(event) => onChatBodyLineHeightChange?.(event.target.value as ChatBodyLineHeightName)} className={selectClass}>
              {CHAT_BODY_LINE_HEIGHT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium text-[var(--text)]">聊天正文字号</span>
            <select aria-label="聊天正文字号" value={chatBodyFontSize} onChange={(event) => onChatBodyFontSizeChange?.(event.target.value as ChatBodyFontSizeName)} className={selectClass}>
              {CHAT_BODY_FONT_SIZE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium text-[var(--text)]">聊天段间距</span>
            <select aria-label="聊天段间距" value={chatBodyParagraphSpacing} onChange={(event) => onChatBodyParagraphSpacingChange?.(event.target.value as ChatBodyParagraphSpacingName)} className={selectClass}>
              {CHAT_BODY_PARAGRAPH_SPACING_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
        </div>
        <label className="flex items-center justify-between gap-3 border-t border-[var(--border)] px-1 py-2">
          <span className="text-sm text-[var(--text)]">Enter 键发送消息</span>
          <input aria-label="Enter 键发送消息" type="checkbox" checked={chatEnterToSend} onChange={(event) => onChatEnterToSendChange?.(event.target.checked)} className="h-4 w-4" />
        </label>
      </fieldset>

      <div className="space-y-3 border-t border-[var(--border)] pt-3">
        <div className="flex items-center gap-2">
          <Bell className="h-5 w-5 text-[var(--accent)]" />
          <div>
            <h3 className="text-base font-semibold text-[var(--text)]">网页通知</h3>
            <p className="text-xs text-[var(--muted)]">全局网页通知开关只保存在当前浏览器。</p>
          </div>
        </div>
        <fieldset disabled={!canManage} className="space-y-3">
          <label className="flex items-center justify-between gap-3 border-t border-[var(--border)] px-1 py-2">
            <span className="text-sm text-[var(--text)]">聊天完成网页通知</span>
            <input aria-label="聊天完成网页通知" type="checkbox" checked={notificationEnabled} onChange={(event) => changeNotification(event.target.checked)} className="h-4 w-4" />
          </label>
          <div className="grid grid-cols-1 gap-3 text-sm text-[var(--muted)] sm:grid-cols-2">
            <div className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">浏览器权限: <span className="font-medium text-[var(--text)]">{permissionText(notificationPermission)}</span></div>
            <div className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">本地开关: <span className="font-medium text-[var(--text)]">{notificationEnabled ? "已开启" : "已关闭"}</span></div>
          </div>
          <button type="button" onClick={() => void requestPermission()} disabled={requestingPermission || notificationPermission === "unsupported"} className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60">
            <Bell className="h-4 w-4" />
            {requestingPermission ? "请求中..." : "请求浏览器通知权限"}
          </button>
        </fieldset>
      </div>
      {notice ? <p role="status" className="text-sm text-[var(--feedback-success-text-deep)]">{notice}</p> : null}
    </section>
  );
}
