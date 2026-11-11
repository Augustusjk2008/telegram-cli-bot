import { Bell, CornerDownLeft, Palette, SlidersHorizontal } from "lucide-react";
import { useId, useState } from "react";
import { ThemeDropdown } from "./ThemeDropdown";
import { DEFAULT_UI_THEME, type UiThemeName } from "../theme";
import {
  getBrowserNotificationPermission,
  readChatCompletionWebNotificationEnabled,
  requestBrowserNotificationPermission,
  writeChatCompletionWebNotificationEnabled,
} from "../utils/chatNotificationEvents";
import type { BrowserNotificationPermission } from "../services/types";
import "./GlobalSettingsPanels.css";

type Props = {
  canManage?: boolean;
  themeName?: UiThemeName;
  onThemeChange?: (themeName: UiThemeName) => void | Promise<void>;
  chatEnterToSend?: boolean;
  onChatEnterToSendChange?: (value: boolean) => void;
};

function permissionText(permission: BrowserNotificationPermission) {
  if (permission === "granted") return "浏览器已允许";
  if (permission === "denied") return "浏览器已拒绝";
  if (permission === "unsupported") return "浏览器不支持";
  return "浏览器未授权";
}

/** Notifications that are switched on but cannot be delivered read as a warning. */
function permissionTone(permission: BrowserNotificationPermission, enabled: boolean) {
  if (permission === "granted") return "success";
  if (permission === "denied") return "danger";
  return enabled ? "warning" : undefined;
}

export function GlobalUiSettingsPanel({
  canManage = true,
  themeName = DEFAULT_UI_THEME,
  onThemeChange,
  chatEnterToSend = true,
  onChatEnterToSendChange,
}: Props) {
  const uid = useId();
  const [notificationEnabled, setNotificationEnabled] = useState(() => readChatCompletionWebNotificationEnabled());
  const [notificationPermission, setNotificationPermission] = useState<BrowserNotificationPermission>(() => getBrowserNotificationPermission());
  const [requestingPermission, setRequestingPermission] = useState(false);
  const [notice, setNotice] = useState("");

  async function changeTheme(value: UiThemeName) {
    if (value === themeName || !onThemeChange) return;
    await onThemeChange(value);
    setNotice("主题选择已更新");
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

  return (
    <section aria-labelledby={`${uid}-title`} className="global-settings-island">
      <header className="global-settings-head">
        <span className="global-settings-head-icon" aria-hidden="true"><SlidersHorizontal className="h-4 w-4" /></span>
        <h2 id={`${uid}-title`}>界面与通知</h2>
      </header>

      <fieldset disabled={!canManage} className="global-settings-list">
        <div className="global-settings-row">
          <span className="global-settings-row-label">
            <Palette className="h-4 w-4" aria-hidden="true" />
            界面主题
          </span>
          <ThemeDropdown
            value={themeName}
            onChange={(value) => void changeTheme(value)}
            className="global-settings-theme"
            menuAlign="right"
          />
        </div>

        <label className="global-settings-row">
          <span className="global-settings-row-label">
            <CornerDownLeft className="h-4 w-4" aria-hidden="true" />
            Enter 键发送消息
          </span>
          <input
            aria-label="Enter 键发送消息"
            type="checkbox"
            checked={chatEnterToSend}
            onChange={(event) => onChatEnterToSendChange?.(event.target.checked)}
          />
        </label>

        <div className="global-settings-row">
          <label htmlFor={`${uid}-notification`} className="global-settings-row-label">
            <Bell className="h-4 w-4" aria-hidden="true" />
            聊天完成网页通知
          </label>
          <div className="global-settings-row-controls">
            <span className="orbit-chip" data-tone={permissionTone(notificationPermission, notificationEnabled)}>
              <span className="global-settings-dot" aria-hidden="true" />
              {permissionText(notificationPermission)}
            </span>
            {notificationPermission === "default" ? (
              <button
                type="button"
                aria-label="请求浏览器通知权限"
                onClick={() => void requestPermission()}
                disabled={requestingPermission}
                className="orbit-btn orbit-btn--secondary orbit-btn--sm"
              >
                {requestingPermission ? "请求中..." : "授权"}
              </button>
            ) : null}
            <input
              id={`${uid}-notification`}
              aria-label="聊天完成网页通知"
              type="checkbox"
              checked={notificationEnabled}
              onChange={(event) => changeNotification(event.target.checked)}
            />
          </div>
        </div>
      </fieldset>

      <p role="status" className="sr-only">{notice}</p>
    </section>
  );
}
