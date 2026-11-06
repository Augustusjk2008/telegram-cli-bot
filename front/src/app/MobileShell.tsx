import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Bug,
  Check,
  ChevronDown,
  Folder,
  GitBranch,
  MessageSquare,
  MonitorSmartphone,
  Settings,
  SquareTerminal,
  type LucideIcon,
} from "lucide-react";
import type { ViewMode } from "./layoutMode";
import type { SessionState } from "../services/types";
import { isGuest } from "../utils/capabilities";
import { AppLogo } from "../components/AppLogo";
import { ThemeIllustrationLayer } from "../theme/ThemeIllustrationLayer";
import "../styles/mobile-shell.css";

export type AppTab = "chat" | "files" | "debug" | "terminal" | "git" | "settings";

const VIEW_MODE_OPTIONS: Array<{ value: ViewMode; label: string }> = [
  { value: "auto", label: "自动" },
  { value: "mobile", label: "竖屏版" },
  { value: "desktop", label: "横屏版" },
];

type Props = {
  session: SessionState | null;
  currentBot: string;
  currentTab: AppTab;
  allowedTabs?: AppTab[];
  hideOuterChrome: boolean;
  activeScreen: ReactNode;
  viewMode: ViewMode;
  hasUnreadOtherBots?: boolean;
  announcementAction?: ReactNode;
  remoteAction?: ReactNode;
  onOpenBotSwitcher: () => void;
  onViewModeChange: (viewMode: ViewMode) => void;
  onTabChange: (tab: AppTab) => void;
};

export function MobileShell({
  session,
  currentBot,
  currentTab,
  allowedTabs,
  hideOuterChrome,
  activeScreen,
  viewMode,
  hasUnreadOtherBots = false,
  announcementAction,
  remoteAction,
  onOpenBotSwitcher,
  onViewModeChange,
  onTabChange,
}: Props) {
  const [viewModeMenuOpen, setViewModeMenuOpen] = useState(false);
  const viewModeRootRef = useRef<HTMLDivElement>(null);
  const viewModeTriggerRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!viewModeMenuOpen) return;
    const closeOnPointerDown = (event: PointerEvent) => {
      if (!viewModeRootRef.current?.contains(event.target as Node)) setViewModeMenuOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setViewModeMenuOpen(false);
        viewModeTriggerRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", closeOnPointerDown);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnPointerDown);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [viewModeMenuOpen]);
  const fullNavItems: Array<{ tab: AppTab; label: string; Icon: LucideIcon }> = [
    { tab: "chat", label: "聊天", Icon: MessageSquare },
    { tab: "files", label: "文件", Icon: Folder },
    { tab: "debug", label: "调试", Icon: Bug },
    { tab: "terminal", label: "终端", Icon: SquareTerminal },
    { tab: "git", label: "Git", Icon: GitBranch },
    { tab: "settings", label: "设置", Icon: Settings },
  ];
  const navItems = isGuest(session)
    ? fullNavItems.filter((item) => item.tab === "chat" || item.tab === "files")
    : fullNavItems.filter((item) => (
        allowedTabs
          ? allowedTabs.includes(item.tab)
          : true
      ));

  const activeViewMode = VIEW_MODE_OPTIONS.find((option) => option.value === viewMode);

  return (
    <div
      data-layout="mobile"
      data-chrome={hideOuterChrome ? "hidden" : "visible"}
      className="mobile-shell orbit-shell relative flex h-[100dvh] w-full min-w-0 flex-col overflow-hidden text-[var(--text)]"
    >
      <div className="orbit-canvas mobile-shell-canvas" aria-hidden="true">
        <ThemeIllustrationLayer surface="workbench" />
      </div>
      {!hideOuterChrome ? (
        <header className="mobile-shell-topbar">
          <button
            type="button"
            onClick={onOpenBotSwitcher}
            className="mobile-shell-bot"
            data-unread={hasUnreadOtherBots ? "true" : undefined}
          >
            {hasUnreadOtherBots ? (
              <span
                data-testid="bot-switcher-unread-indicator"
                aria-hidden="true"
                className="mobile-shell-unread"
              />
            ) : null}
            <span className="mobile-shell-bot-badge" aria-hidden="true">
              <AppLogo size={18} decorative />
            </span>
            <span className="mobile-shell-bot-name">{currentBot}</span>
            <ChevronDown className="mobile-shell-bot-chevron" aria-hidden="true" />
          </button>
          <div ref={viewModeRootRef} className="mobile-shell-actions">
            {remoteAction}
            {announcementAction}
            <button
              ref={viewModeTriggerRef}
              type="button"
              aria-label="视图模式"
              aria-haspopup="menu"
              aria-expanded={viewModeMenuOpen}
              title={`视图模式：${activeViewMode?.label ?? ""}`}
              onClick={() => setViewModeMenuOpen((value) => !value)}
              className="mobile-shell-icon-button"
            >
              <MonitorSmartphone className="h-4 w-4" aria-hidden="true" />
            </button>
            {viewModeMenuOpen ? (
              <div role="menu" aria-label="视图模式" className="mobile-shell-menu">
                {VIEW_MODE_OPTIONS.map(({ value: nextMode, label }) => (
                  <button
                    key={nextMode}
                    type="button"
                    role="menuitemradio"
                    aria-checked={viewMode === nextMode}
                    onClick={() => {
                      onViewModeChange(nextMode);
                      setViewModeMenuOpen(false);
                      viewModeTriggerRef.current?.focus();
                    }}
                    className="mobile-shell-menu-item"
                  >
                    <span>{label}</span>
                    {viewMode === nextMode ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : null}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        </header>
      ) : null}

      <div className="mobile-shell-stage">
        {activeScreen}
      </div>

      {!hideOuterChrome ? (
        <nav className="mobile-shell-tabbar" aria-label="主导航">
          {navItems.map(({ tab, label, Icon }) => (
            <button
              key={tab}
              type="button"
              onClick={() => onTabChange(tab)}
              aria-current={currentTab === tab ? "page" : undefined}
              className="mobile-shell-tab"
            >
              <span className="mobile-shell-tab-icon" aria-hidden="true">
                <Icon className="h-[18px] w-[18px]" />
              </span>
              <span className="mobile-shell-tab-label">{label}</span>
            </button>
          ))}
        </nav>
      ) : null}
    </div>
  );
}
